"""Tests for Reciprocal Rank Fusion, with scores computed by hand."""

import math

import pytest

from masdar.domain.amendments import ArticleStatus
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.fusion import RRF_K, reciprocal_rank_fusion, validate_weights
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber


def chunk(name: str) -> Chunk:
    article = Article("law", "نظام", ArticleNumber(1), "المادة", "نص", ArticleStatus.IN_FORCE)
    return Chunk(name, article, "نص", "نص")


def ranked(*names: str, retriever: str = "r") -> list[Hit]:
    return [Hit(chunk(name), 1.0, rank, retriever) for rank, name in enumerate(names, start=1)]


def ids(hits: list[Hit]) -> list[str]:
    return [hit.chunk.chunk_id for hit in hits]


def test_default_k_is_the_papers_value() -> None:
    assert RRF_K == 60


def test_scores_match_the_formula() -> None:
    fused = reciprocal_rank_fusion([ranked("A", "B", "C"), ranked("C", "A")])
    # A: 1/61 + 1/62, C: 1/63 + 1/61, B: 1/62 only.
    assert ids(fused) == ["A", "C", "B"]
    assert fused[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert fused[1].score == pytest.approx(1 / 63 + 1 / 61)
    assert fused[2].score == pytest.approx(1 / 62)
    assert [hit.rank for hit in fused] == [1, 2, 3]
    assert {hit.retriever for hit in fused} == {"rrf"}


def test_exact_tie_is_broken_by_chunk_id_whatever_the_input_order() -> None:
    first = reciprocal_rank_fusion([ranked("B", "A"), ranked("A", "B")])
    second = reciprocal_rank_fusion([ranked("A", "B"), ranked("B", "A")])
    assert first[0].score == second[0].score == pytest.approx(1 / 61 + 1 / 62)
    assert ids(first) == ids(second) == ["A", "B"]


def test_weights_scale_each_list() -> None:
    fused = reciprocal_rank_fusion([ranked("A"), ranked("B")], weights=[1.0, 2.0])
    assert ids(fused) == ["B", "A"]
    assert fused[0].score == pytest.approx(2 / 61)
    assert fused[1].score == pytest.approx(1 / 61)


def test_zero_weight_keeps_the_hits_but_adds_nothing() -> None:
    fused = reciprocal_rank_fusion([ranked("A"), ranked("B")], weights=[0.0, 1.0])
    assert ids(fused) == ["B", "A"]
    assert fused[1].score == 0.0


def test_custom_k() -> None:
    fused = reciprocal_rank_fusion([ranked("A")], k=1)
    assert fused[0].score == pytest.approx(1 / 2)


def test_uses_each_hits_own_rank_not_its_position() -> None:
    # A list filtered after ranking keeps its gaps: C was ranked 3rd.
    gapped = [Hit(chunk("C"), 1.0, 3, "r")]
    assert reciprocal_rank_fusion([gapped])[0].score == pytest.approx(1 / 63)


def test_duplicate_chunk_in_one_list_counts_once_at_its_best_rank() -> None:
    fused = reciprocal_rank_fusion([ranked("A", "B", "A")])
    assert ids(fused) == ["A", "B"]
    assert fused[0].score == pytest.approx(1 / 61)


def test_keeps_the_chunk_object_and_stamps_the_name() -> None:
    hits = ranked("A")
    fused = reciprocal_rank_fusion([hits], retriever="hybrid(x)")
    assert fused[0].chunk is hits[0].chunk
    assert fused[0].retriever == "hybrid(x)"


def test_empty_inputs() -> None:
    assert reciprocal_rank_fusion([]) == []
    assert reciprocal_rank_fusion([[], []]) == []


@pytest.mark.parametrize("k", [0, -1, True])
def test_rejects_bad_k(k: int) -> None:
    with pytest.raises(InvalidDomainObjectError, match="k must be"):
        reciprocal_rank_fusion([ranked("A")], k=k)


@pytest.mark.parametrize("weights", [[1.0], [1.0, -0.5], [1.0, math.nan], [math.inf, 1.0]])
def test_rejects_bad_weights(weights: list[float]) -> None:
    with pytest.raises(InvalidDomainObjectError):
        reciprocal_rank_fusion([ranked("A"), ranked("B")], weights=weights)


def test_validate_weights_defaults_to_equal() -> None:
    assert validate_weights(None, 3) == (1.0, 1.0, 1.0)
    assert validate_weights([0.5, 2], 2) == (0.5, 2)
