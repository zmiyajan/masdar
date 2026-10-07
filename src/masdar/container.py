"""Composition root: the only module that builds adapters and wires use cases.

Keeping all construction here means use cases never know which concrete
adapters they run with, and tests can wire fakes the same way.
"""

import ssl
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from functools import partial
from pathlib import Path

import httpx
import truststore

from masdar.adapters.beir_writer import BeirDatasetWriter
from masdar.adapters.bm25 import Bm25Retriever, arabic_analyzer, display_text, whitespace_analyzer
from masdar.adapters.boe.client import BoeClient
from masdar.adapters.boe.source import BoeLawSource
from masdar.adapters.eval_writer import EvalResultsWriter
from masdar.adapters.gold_jsonl import JsonlGoldSource
from masdar.app.build_dataset import BuildDataset
from masdar.app.corpus import Corpus, load_corpus
from masdar.app.evaluate import Evaluate
from masdar.app.search import SearchService
from masdar.config import Settings
from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.chunking import ChunkingOptions
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
    with httpx.Client() as http:
        client = BoeClient(
            http, settings.snapshot_dir, crawl_delay=settings.crawl_delay_seconds, offline=True
        )
        source = BoeLawSource(client, settings.snapshot_dir)
        return load_corpus(source, ArabicNormalizer(), chunking or ChunkingOptions())


# ----------------------------------------------------------------- search pipelines

EVAL_DIR = Path("eval")
"""Where ``masdar eval`` writes results; relative to the working directory."""


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
    corpus = load_current_corpus(settings, chunking=ChunkingOptions(include_context=context))
    tokenizer = ArabicTokenizer(TokenizerOptions(stopwords=stopwords, stemming=stemming))
    retriever = Bm25Retriever(
        corpus.chunks,
        name=_bm25_name(stemming=stemming, context=context, stopwords=stopwords),
        analyzer=arabic_analyzer(tokenizer=tokenizer),
    )
    return SearchService(retriever)


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
"""The lexical ablation, weakest to strongest; ``masdar eval`` runs these by name."""


def default_search_service(settings: Settings | None = None) -> SearchService:
    """The pipeline the API, the CLI and the MCP server serve.

    Args:
        settings: Defaults to `Settings()` read from the environment.
    """
    return bm25_search_service(settings or Settings())


def evaluate_use_case(settings: Settings) -> Evaluate:
    """The evaluation use case over the configured gold set."""
    return Evaluate(JsonlGoldSource(settings.gold_path))


def eval_results_writer(eval_dir: Path = EVAL_DIR) -> EvalResultsWriter:
    """Writes ``results/*.json``, ``RESULTS.md`` and ``baseline.json`` under ``eval_dir``."""
    return EvalResultsWriter(eval_dir)
