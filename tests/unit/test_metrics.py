"""Ranking metrics, checked against values computed by hand."""

import math
from collections.abc import Callable, Mapping, Sequence

import pytest

from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.metrics import first_rank, ndcg_at_k, recall_at_k, reciprocal_rank_at_k

GRADES = {"a": 2, "c": 1}  # a answers, c is related
Metric = Callable[[Sequence[str], Mapping[str, int], int], float]


class TestRecall:
    @pytest.mark.parametrize(
        ("k", "expected"),
        [(1, 1 / 3), (2, 1 / 3), (3, 2 / 3), (10, 2 / 3)],
    )
    def test_counts_every_graded_article(self, k: int, expected: float) -> None:
        assert recall_at_k(["a", "x", "b"], {"a": 2, "b": 1, "c": 1}, k) == pytest.approx(expected)

    def test_no_relevant_articles_scores_zero(self) -> None:
        assert recall_at_k(["a"], {}, 10) == 0.0


class TestReciprocalRank:
    def test_first_relevant_article_counts_even_if_only_related(self) -> None:
        assert reciprocal_rank_at_k(["x", "c", "a"], GRADES, 10) == 0.5

    def test_relevant_article_below_the_cutoff_scores_zero(self) -> None:
        assert reciprocal_rank_at_k(["x", "y", "a"], GRADES, 2) == 0.0

    def test_empty_ranking_scores_zero(self) -> None:
        assert reciprocal_rank_at_k([], GRADES, 10) == 0.0


class TestNdcg:
    IDEAL = 2 + 1 / math.log2(3)  # a at rank 1, c at rank 2

    def test_perfect_ranking_scores_one(self) -> None:
        assert ndcg_at_k(["a", "c", "x"], GRADES, 10) == pytest.approx(1.0)

    def test_hand_computed_value(self) -> None:
        # DCG = 2/log2(2) + 0/log2(3) + 1/log2(4) = 2.5
        assert ndcg_at_k(["a", "x", "c"], GRADES, 10) == pytest.approx(2.5 / self.IDEAL)
        assert ndcg_at_k(["a", "x", "c"], GRADES, 10) == pytest.approx(0.95023, abs=1e-5)

    def test_grades_reward_the_answer_first(self) -> None:
        # DCG = 1/log2(2) + 2/log2(3) = 2.26186; swapping a and c costs 0.09.
        assert ndcg_at_k(["c", "a"], GRADES, 10) == pytest.approx(0.85972, abs=1e-5)

    def test_ideal_is_cut_at_k(self) -> None:
        # At k = 1 the ideal is a alone (gain 2); returning c gives 1/2.
        assert ndcg_at_k(["c", "a"], GRADES, 1) == pytest.approx(0.5)

    def test_missing_judged_articles_cost_score(self) -> None:
        assert ndcg_at_k(["a"], GRADES, 10) == pytest.approx(2 / self.IDEAL)

    def test_nothing_relevant_returned_scores_zero(self) -> None:
        assert ndcg_at_k(["x", "y"], GRADES, 10) == 0.0

    def test_no_judgments_scores_zero(self) -> None:
        assert ndcg_at_k(["a"], {}, 10) == 0.0


class TestFirstRank:
    def test_finds_the_first_article_at_the_grade(self) -> None:
        assert first_rank(["x", "c", "a"], GRADES, grade=2) == 3
        assert first_rank(["x", "c", "a"], GRADES, grade=1) == 2

    def test_none_when_absent(self) -> None:
        assert first_rank(["x", "c"], GRADES, grade=2) is None


class TestValidation:
    @pytest.mark.parametrize("metric", [recall_at_k, reciprocal_rank_at_k, ndcg_at_k])
    def test_rejects_a_cutoff_below_one(self, metric: Metric) -> None:
        with pytest.raises(InvalidDomainObjectError, match="k must be"):
            metric(["a"], GRADES, 0)

    @pytest.mark.parametrize("metric", [recall_at_k, reciprocal_rank_at_k, ndcg_at_k])
    def test_rejects_duplicate_articles(self, metric: Metric) -> None:
        # A duplicate would let one article be counted twice in DCG.
        with pytest.raises(InvalidDomainObjectError, match="repeat"):
            metric(["a", "a"], GRADES, 10)
