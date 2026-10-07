"""Composition root: the only module that builds adapters and wires use cases.

Keeping all construction here means use cases never know which concrete
adapters they run with, and tests can wire fakes the same way.
"""

import importlib.util
import json
import ssl
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import cache, partial
from pathlib import Path

import httpx
import truststore

from masdar.adapters.beir_writer import BeirDatasetWriter
from masdar.adapters.bm25 import Bm25Retriever, arabic_analyzer, display_text, whitespace_analyzer
from masdar.adapters.boe.client import BoeClient
from masdar.adapters.boe.source import BoeLawSource
from masdar.adapters.clauses_jsonl import JsonlLabeledClauseSource
from masdar.adapters.cross_encoder import (
    DEFAULT_ANSWER_THRESHOLD,
    DEFAULT_RERANK_CANDIDATES,
    CrossEncoderReranker,
)
from masdar.adapters.dense import DenseRetriever
from masdar.adapters.eval_writer import EvalResultsWriter
from masdar.adapters.files import write_atomically
from masdar.adapters.gold_jsonl import JsonlGoldSource
from masdar.adapters.out_of_scope_jsonl import JsonlOutOfScopeSource
from masdar.app.answer import AnswerService, measure_answers
from masdar.app.build_dataset import BuildDataset
from masdar.app.check_contract import CheckContract, measure_checker
from masdar.app.corpus import Corpus, load_corpus
from masdar.app.evaluate import Evaluate
from masdar.app.hybrid import HybridRetriever
from masdar.app.search import SearchService
from masdar.config import ROBOTS_CRAWL_DELAY_SECONDS, Settings
from masdar.domain.answer import AnswerQualityReport
from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.checker_quality import CheckerQualityReport
from masdar.domain.chunking import ChunkingOptions
from masdar.domain.errors import MasdarError
from masdar.domain.labor_rules import LABOR_RULES
from masdar.domain.tokenize import ArabicTokenizer, TokenizerOptions


@contextmanager
def dataset_builder(
    settings: Settings, *, offline: bool = False, refresh: bool = False
) -> Iterator[BuildDataset]:
    """Yield a ready `BuildDataset`; the HTTP client is closed on exit.

    Args:
        settings: Validated application settings.
        offline: Use only the committed snapshots; never touch the network.
        refresh: Re-download every page (ignored when ``offline``).
    """
    # The portal does not send its intermediate certificate, so certifi's bundle
    # cannot build the chain. The OS trust store can (it fetches intermediates);
    # verification stays fully on. See ADR-0002.
    tls = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with httpx.Client(
        headers={"User-Agent": settings.user_agent},
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        verify=tls,
    ) as http:
        client = BoeClient(
            http,
            settings.snapshot_dir,
            crawl_delay=settings.crawl_delay_seconds,
            offline=offline,
        )
        yield BuildDataset(
            source=BoeLawSource(client, settings.snapshot_dir, refresh=refresh and not offline),
            writer=BeirDatasetWriter(settings.dataset_dir),
            normalizer=ArabicNormalizer(),
            chunking=ChunkingOptions(),
            gold=JsonlGoldSource(settings.gold_path),
        )


def load_current_corpus(settings: Settings, *, chunking: ChunkingOptions | None = None) -> Corpus:
    """Current articles and chunks, built offline from the committed snapshots.

    Retrievers, the API, the MCP server and the evaluation all index exactly
    this corpus, so they agree on what "the law" is.

    Args:
        settings: Validated application settings.
        chunking: Chunking parameters; defaults to `ChunkingOptions()`. The
            evaluation passes other options to measure their effect.
    """
    return _corpus(settings.snapshot_dir, chunking or ChunkingOptions())


@cache
def _corpus(snapshot_dir: Path, chunking: ChunkingOptions) -> Corpus:
    # Memoized: the corpus is immutable and every pipeline, the MCP server and
    # the evaluation need it, so parsing the snapshots once per process is enough.
    with httpx.Client() as http:
        client = BoeClient(http, snapshot_dir, crawl_delay=ROBOTS_CRAWL_DELAY_SECONDS, offline=True)
        source = BoeLawSource(client, snapshot_dir)
        return load_corpus(source, ArabicNormalizer(), chunking)


# ----------------------------------------------------------------- search pipelines


def bm25_search_service(
    settings: Settings, *, stemming: bool = True, context: bool = True, stopwords: bool = True
) -> SearchService:
    """A BM25 pipeline over the normalized chunk text.

    The defaults are the measured best lexical configuration (ADR-0006); the
    switches exist so the evaluation can show what each technique adds.

    Args:
        settings: Validated application settings.
        stemming: Apply light10 stemming to documents and queries.
        context: Index each chunk with its law/part/chapter/heading prefix.
        stopwords: Drop Arabic function words before stemming.
    """
    return SearchService(
        _bm25_retriever(settings, stemming=stemming, context=context, stopwords=stopwords)
    )


def _bm25_retriever(
    settings: Settings, *, stemming: bool = True, context: bool = True, stopwords: bool = True
) -> Bm25Retriever:
    corpus = load_current_corpus(settings, chunking=ChunkingOptions(include_context=context))
    tokenizer = ArabicTokenizer(TokenizerOptions(stopwords=stopwords, stemming=stemming))
    return Bm25Retriever(
        corpus.chunks,
        name=_bm25_name(stemming=stemming, context=context, stopwords=stopwords),
        analyzer=arabic_analyzer(tokenizer=tokenizer),
    )


def bm25_raw_search_service(settings: Settings) -> SearchService:
    """The floor of the ablation: original text, whitespace tokens, nothing Arabic-aware."""
    corpus = load_current_corpus(settings, chunking=ChunkingOptions(include_context=False))
    return SearchService(
        Bm25Retriever(
            corpus.chunks, name="bm25-raw", analyzer=whitespace_analyzer, text_of=display_text
        )
    )


def _bm25_name(*, stemming: bool, context: bool, stopwords: bool) -> str:
    if stemming and context:
        return "bm25" if stopwords else "bm25-keep-stopwords"
    name = "bm25-normalized" + ("+context" if context else "") + ("+light10" if stemming else "")
    return name if stopwords else f"{name}+keep-stopwords"


LEXICAL_PIPELINES: Mapping[str, Callable[[Settings], SearchService]] = {
    "bm25-raw": bm25_raw_search_service,
    "bm25-normalized": partial(bm25_search_service, stemming=False, context=False),
    "bm25-normalized+context": partial(bm25_search_service, stemming=False),
    "bm25-keep-stopwords": partial(bm25_search_service, stopwords=False),
    "bm25": bm25_search_service,
}
"""The lexical ablation, weakest to strongest. Needs no ML dependencies."""


def dense_search_service(
    settings: Settings, *, hybrid: bool = False, rerank: bool = False
) -> SearchService:
    """A semantic pipeline: mE5 dense retrieval, optionally fused and reranked (ADR-0007).

    Args:
        settings: Validated application settings.
        hybrid: Fuse dense with the best BM25 pipeline by reciprocal rank fusion.
        rerank: Reorder the top candidates with the cross-encoder.

    Raises:
        MasdarError: If the ``ml`` extra (sentence-transformers) is not installed.
    """
    if importlib.util.find_spec("sentence_transformers") is None:
        raise MasdarError(
            "semantic pipelines need the ml extra: run `uv sync --extra ml`, "
            "or set MASDAR_PIPELINE=bm25"
        )
    corpus = load_current_corpus(settings)
    retriever: DenseRetriever | HybridRetriever = DenseRetriever.from_chunks(
        corpus.chunks, cache_dir=settings.index_dir
    )
    if hybrid:
        retriever = HybridRetriever([_bm25_retriever(settings), retriever])
    if not rerank:
        return SearchService(retriever)
    return SearchService(
        retriever, CrossEncoderReranker.from_model(), candidates=DEFAULT_RERANK_CANDIDATES
    )


SEMANTIC_PIPELINES: Mapping[str, Callable[[Settings], SearchService]] = {
    "dense": dense_search_service,
    "hybrid(bm25+dense)": partial(dense_search_service, hybrid=True),
    "dense+rerank": partial(dense_search_service, rerank=True),
    "hybrid(bm25+dense)+rerank": partial(dense_search_service, hybrid=True, rerank=True),
}
"""Dense, fused and reranked pipelines. Need the ``ml`` extra."""

PIPELINES: Mapping[str, Callable[[Settings], SearchService]] = {
    **LEXICAL_PIPELINES,
    **SEMANTIC_PIPELINES,
}
"""Every pipeline by name, weakest to strongest; each name equals its `SearchService.name`."""


def search_service(settings: Settings, name: str) -> SearchService:
    """Build the pipeline registered as ``name``.

    Raises:
        MasdarError: If no pipeline has that name.
    """
    try:
        build = PIPELINES[name]
    except KeyError:
        raise MasdarError(f"unknown pipeline {name!r}; choose one of {list(PIPELINES)}") from None
    return build(settings)


def default_search_service(settings: Settings | None = None) -> SearchService:
    """The pipeline the API, the CLI and the MCP server serve (``Settings.pipeline``).

    Args:
        settings: Defaults to `Settings()` read from the environment.
    """
    settings = settings or Settings()
    return search_service(settings, settings.pipeline)


def evaluate_use_case(settings: Settings) -> Evaluate:
    """The evaluation use case over the configured gold set."""
    return Evaluate(JsonlGoldSource(settings.gold_path))


def eval_results_writer(eval_dir: Path) -> EvalResultsWriter:
    """Writes ``results/*.json``, ``RESULTS.md`` and ``baseline.json`` under ``eval_dir``."""
    return EvalResultsWriter(eval_dir)


def answer_service(search: SearchService) -> AnswerService | None:
    """Extractive answers on top of an already built search pipeline (ADR-0009).

    The answer threshold is calibrated on the cross-encoder's logits, so answers
    exist only for pipelines that rerank with it; for any other pipeline this
    returns ``None`` and callers offer search alone. Reusing the reranker's
    scorer means the model is loaded once.

    Args:
        search: The served pipeline, e.g. from `default_search_service`.
    """
    reranker = search.reranker
    if not isinstance(reranker, CrossEncoderReranker):
        return None
    return AnswerService(search, reranker.scorer, threshold=DEFAULT_ANSWER_THRESHOLD)


def answer_quality(settings: Settings, service: AnswerService) -> AnswerQualityReport:
    """Measure ``service`` on the gold questions and the out-of-scope set."""
    return measure_answers(
        service,
        JsonlGoldSource(settings.gold_path).load(),
        JsonlOutOfScopeSource(settings.out_of_scope_path).load(),
    )


def check_contract_use_case(search: SearchService) -> CheckContract:
    """The contract checker with the Labor Law rules (ADR-0010).

    Verdicts never depend on retrieval; the related articles shown under each
    clause come from the served pipeline's first stage only. A contract can
    hold dozens of clauses, and reranking each one would cost about half a
    second of CPU apiece on the demo hardware.

    Args:
        search: The served pipeline; its first-stage retriever is reused.
    """
    return CheckContract(SearchService(search.retriever), LABOR_RULES)


def checker_quality(settings: Settings) -> dict[str, CheckerQualityReport]:
    """Verdict quality on every configured labeled clause set, by set name."""
    return {
        name: measure_checker(JsonlLabeledClauseSource(path).load(), LABOR_RULES)
        for name, path in settings.clause_sets.items()
    }


def save_quality_report(name: str, document: Mapping[str, object], eval_dir: Path) -> Path:
    """Write ``<name>.json`` next to the retrieval results; returns its path."""
    path = eval_dir / f"{name}.json"
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
    write_atomically(path, (text + "\n").encode("utf-8"))
    return path
