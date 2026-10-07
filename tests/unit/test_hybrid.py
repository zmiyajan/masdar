"""Tests for the hybrid retriever, on fake child retrievers."""

import pytest

from masdar.app.hybrid import DEFAULT_FUSION_DEPTH, HybridRetriever
from masdar.domain.amendments import ArticleStatus
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber


def chunk(name: str) -> Chunk:
    article = Article("law", "نظام", ArticleNumber(1), "المادة", "نص", ArticleStatus.IN_FORCE)
    return Chunk(name, article, "نص", "نص")


class FakeRetriever:
    def __init__(self, name: str, order: list[str]) -> None:
        self._name = name
        self._order = order
        self.requested: list[int] = []
        self.queries: list[str] = []

    @property
    def name(self) -> str:
        return self._name

    def search(self, query: str, k: int) -> list[Hit]:
        self.requested.append(k)
        self.queries.append(query)
        return [
            Hit(chunk(chunk_id), 1.0, rank, self._name)
            for rank, chunk_id in enumerate(self._order[:k], start=1)
        ]


def test_name_lists_the_children() -> None:
    hybrid = HybridRetriever([FakeRetriever("bm25", []), FakeRetriever("dense", [])])
    assert hybrid.name == "hybrid(bm25+dense)"


def test_fuses_children_with_rrf_and_cuts_to_k() -> None:
    bm25 = FakeRetriever("bm25", ["A", "B", "C"])
    dense = FakeRetriever("dense", ["C", "A", "D"])
    hits = HybridRetriever([bm25, dense]).search("سؤال", 2)
    assert [hit.chunk.chunk_id for hit in hits] == ["A", "C"]
    assert hits[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert [hit.rank for hit in hits] == [1, 2]
    assert {hit.retriever for hit in hits} == {"hybrid(bm25+dense)"}


def test_asks_children_for_depth_or_k_whichever_is_larger() -> None:
    child = FakeRetriever("bm25", ["A"])
    hybrid = HybridRetriever([child], depth=5)
    hybrid.search("سؤال", 3)
    hybrid.search("سؤال", 8)
    assert child.requested == [5, 8]
    assert child.queries == ["سؤال", "سؤال"]
    assert DEFAULT_FUSION_DEPTH == 100


def test_weights_favour_one_child() -> None:
    bm25 = FakeRetriever("bm25", ["A"])
    dense = FakeRetriever("dense", ["B"])
    hits = HybridRetriever([bm25, dense], weights=[1.0, 2.0]).search("سؤال", 2)
    assert [hit.chunk.chunk_id for hit in hits] == ["B", "A"]


def test_non_positive_k_returns_nothing_without_calling_children() -> None:
    child = FakeRetriever("bm25", ["A"])
    assert HybridRetriever([child]).search("سؤال", 0) == []
    assert child.requested == []


def test_rejects_bad_configuration() -> None:
    child = FakeRetriever("bm25", [])
    with pytest.raises(InvalidDomainObjectError, match="at least one"):
        HybridRetriever([])
    with pytest.raises(InvalidDomainObjectError, match="depth"):
        HybridRetriever([child], depth=0)
    with pytest.raises(InvalidDomainObjectError, match="weights"):
        HybridRetriever([child], weights=[1.0, 1.0])
    with pytest.raises(InvalidDomainObjectError, match="weights"):
        HybridRetriever([child], weights=[-1.0])
