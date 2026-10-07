"""Tests for the cross-encoder reranker, on a fake pair scorer."""

from collections.abc import Sequence

import pytest

from masdar.adapters.cross_encoder import (
    DEFAULT_RERANK_CANDIDATES,
    DEFAULT_RERANKER_MODEL,
    CrossEncoderReranker,
    passage,
)
from masdar.domain.amendments import ArticleStatus
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber


def hit(number: int, text: str, rank: int) -> Hit:
    article = Article(
        "labor-law",
        "نظام العمل",
        ArticleNumber(number),
        f"المادة {number}",
        text,
        ArticleStatus.IN_FORCE,
        part="الباب الأول",
    )
    return Hit(Chunk(f"labor-law:{number}#0", article, text, "normalized"), 0.5, rank, "hybrid")


class OverlapScorer:
    """Deterministic fake: scores a pair by shared words; records every call."""

    def __init__(self) -> None:
        self.calls: list[list[tuple[str, str]]] = []

    def score(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        self.calls.append(list(pairs))
        return [float(len(set(q.split()) & set(p.split()))) for q, p in pairs]


HITS = [hit(1, "عقد", 1), hit(2, "اجازة وضع", 2), hit(3, "اجازة", 3)]


def test_defaults() -> None:
    assert DEFAULT_RERANKER_MODEL == "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
    assert DEFAULT_RERANK_CANDIDATES == 30


def test_passage_is_location_then_text() -> None:
    assert passage(HITS[0].chunk) == "نظام العمل | الباب الأول | المادة 1\nعقد"


def test_reorders_by_score_and_renumbers() -> None:
    scorer = OverlapScorer()
    reranked = CrossEncoderReranker(scorer).rerank(" اجازة وضع ", HITS, 3)
    assert [h.chunk.chunk_id for h in reranked] == [
        "labor-law:2#0",
        "labor-law:3#0",
        "labor-law:1#0",
    ]
    assert [h.score for h in reranked] == [2.0, 1.0, 0.0]
    assert [h.rank for h in reranked] == [1, 2, 3]
    assert {h.retriever for h in reranked} == {"rerank"}
    assert scorer.calls == [[("اجازة وضع", passage(h.chunk)) for h in HITS]]


def test_ties_keep_first_stage_order() -> None:
    reranked = CrossEncoderReranker(OverlapScorer()).rerank("غير", HITS[::-1], 3)
    assert [h.chunk.chunk_id for h in reranked] == [h.chunk.chunk_id for h in HITS]


def test_cuts_to_k_and_handles_short_lists() -> None:
    reranker = CrossEncoderReranker(OverlapScorer(), name="ce")
    assert reranker.name == "ce"
    assert len(reranker.rerank("اجازة", HITS, 1)) == 1
    assert len(reranker.rerank("اجازة", HITS, 10)) == len(HITS)


def test_empty_input_or_k_skips_the_model() -> None:
    scorer = OverlapScorer()
    reranker = CrossEncoderReranker(scorer)
    assert reranker.rerank("اجازة", [], 5) == []
    assert reranker.rerank("اجازة", HITS, 0) == []
    assert scorer.calls == []


def test_rejects_a_scorer_returning_the_wrong_count() -> None:
    class Broken:
        def score(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
            return [1.0] * (len(pairs) - 2)

    with pytest.raises(InvalidDomainObjectError, match="1 scores for 3"):
        CrossEncoderReranker(Broken()).rerank("اجازة", HITS, 3)
