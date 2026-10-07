"""Sanity checks with the real default models (slow: downloads them on first run).

Run with ``make test-slow``. They guard the wiring that fakes cannot: E5
prefixes, the device, the cache, and that the models really bridge wording
the law does not use.
"""

from pathlib import Path

import pytest

from masdar.adapters.cross_encoder import DEFAULT_RERANK_CANDIDATES, CrossEncoderReranker
from masdar.adapters.dense import DenseRetriever
from masdar.app.corpus import Corpus
from masdar.app.search import SearchService
from masdar.config import Settings
from masdar.container import load_current_corpus
from masdar.domain.models import Hit

pytestmark = pytest.mark.slow

# Paraphrase gold question q028: the law says "إجازة وضع", never "الأمومة".
MATERNITY = "كم مدة إجازة الأمومة للموظفة؟"
MATERNITY_ARTICLE = "labor-law:151"


@pytest.fixture(scope="module")
def corpus(snapshot_dir: Path) -> Corpus:
    pytest.importorskip("sentence_transformers")
    return load_current_corpus(Settings(snapshot_dir=snapshot_dir))


@pytest.fixture(scope="module")
def dense(corpus: Corpus, tmp_path_factory: pytest.TempPathFactory) -> DenseRetriever:
    return DenseRetriever.from_chunks(corpus.chunks, cache_dir=tmp_path_factory.mktemp("index"))


@pytest.fixture(scope="module")
def reranker() -> CrossEncoderReranker:
    pytest.importorskip("sentence_transformers")
    return CrossEncoderReranker.from_model()


def article_ids(service: SearchService, query: str, k: int = 10) -> list[str]:
    return [result.article.article_id for result in service.search(query, k)]


def test_dense_bridges_a_paraphrase(dense: DenseRetriever) -> None:
    service = SearchService(dense, candidates=DEFAULT_RERANK_CANDIDATES)
    assert MATERNITY_ARTICLE in article_ids(service, MATERNITY)


def test_dense_scores_are_cosines(dense: DenseRetriever) -> None:
    hits = dense.search(MATERNITY, 5)
    assert all(-1.0 <= hit.score <= 1.0 + 1e-6 for hit in hits)
    assert [hit.score for hit in hits] == sorted((hit.score for hit in hits), reverse=True)


def test_a_rebuild_reads_the_cache(dense: DenseRetriever, corpus: Corpus) -> None:
    assert dense.cache_path is not None
    assert dense.cache_path.exists()
    rebuilt = DenseRetriever.from_chunks(corpus.chunks, cache_dir=dense.cache_path.parent)
    assert rebuilt.cache_path == dense.cache_path
    assert rebuilt.search(MATERNITY, 10) == dense.search(MATERNITY, 10)


def test_reranked_pipeline_keeps_the_answer_in_the_top_10(
    dense: DenseRetriever, reranker: CrossEncoderReranker
) -> None:
    # Known weakness (ADR-0007): the small reranker moves this answer from rank 1
    # to rank 7, because it does not link "الأمومة" to "وضع". It must not lose it.
    service = SearchService(dense, reranker, candidates=DEFAULT_RERANK_CANDIDATES)
    assert MATERNITY_ARTICLE in article_ids(service, MATERNITY)


def test_reranker_prefers_the_answer_to_an_unrelated_article(
    dense: DenseRetriever, reranker: CrossEncoderReranker, corpus: Corpus
) -> None:
    answer = next(
        h for h in dense.search(MATERNITY, 30) if h.chunk.chunk_id.startswith("labor-law:151#")
    )
    unrelated = next(c for c in corpus.chunks if c.article.law_id == "companies-law")
    candidates = [Hit(unrelated, 1.0, 1, "fake"), Hit(answer.chunk, 0.5, 2, "fake")]
    assert reranker.rerank(MATERNITY, candidates, 2)[0].chunk == answer.chunk
