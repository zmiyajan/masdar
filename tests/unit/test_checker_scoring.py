"""Tests for scoring the contract checker against labeled clauses."""

import pytest

from masdar.domain.checker_quality import (
    LabeledClause,
    parse_labeled_clause,
    score_checker,
)
from masdar.domain.compliance import FindingKind
from masdar.domain.errors import InvalidDomainObjectError

V, C, R = FindingKind.VIOLATION, FindingKind.COMPLIANT, FindingKind.REVIEW_NEEDED


def clause(clause_id: str, *expected: tuple[str, FindingKind]) -> LabeledClause:
    return LabeledClause(clause_id, "نص", frozenset(expected))


class TestParse:
    def test_reads_a_record(self) -> None:
        record = {
            "_id": "cl-001",
            "text": "نص",
            "expected": [{"rule_id": "probation-max", "kind": "violation"}],
            "note": "n",
        }
        parsed = parse_labeled_clause(record)
        assert parsed.expected == frozenset({("probation-max", V)})
        assert parsed.note == "n"

    @pytest.mark.parametrize(
        "record",
        [
            {"text": "نص", "expected": []},
            {"_id": "c", "text": 3, "expected": []},
            {"_id": "c", "text": "نص", "expected": "none"},
            {"_id": "c", "text": "نص", "expected": ["x"]},
            {"_id": "c", "text": "نص", "expected": [{"rule_id": "r", "kind": "maybe"}]},
            {"_id": "c", "text": "نص", "expected": [{"kind": "violation"}]},
            {"_id": " ", "text": "نص", "expected": []},
        ],
    )
    def test_rejects_bad_records(self, record: dict[str, object]) -> None:
        with pytest.raises(InvalidDomainObjectError):
            parse_labeled_clause(record)


def test_precision_recall_and_exact_accuracy() -> None:
    labeled = [
        clause("a", ("r1", V)),
        clause("b", ("r2", C)),
        clause("c"),
        clause("d", ("r3", R)),
    ]
    predicted = [
        {("r1", V)},  # exact
        {("r2", V)},  # wrong verdict: a false violation and a missed compliant
        set(),  # exact
        {("r3", R), ("r4", C)},  # one extra
    ]
    report = score_checker(labeled, predicted)
    assert (report.clauses, report.exact, report.exact_accuracy) == (4, 2, 0.5)
    violation = report.score(V)
    assert (violation.correct, violation.predicted, violation.expected) == (1, 2, 1)
    assert (violation.precision, violation.recall) == (0.5, 1.0)
    assert (report.score(C).precision, report.score(C).recall) == (0.0, 0.0)
    assert (report.score(R).precision, report.score(R).recall) == (1.0, 1.0)
    assert [miss.clause_id for miss in report.misses] == ["b", "d"]


def test_empty_counts_are_perfect_by_convention() -> None:
    report = score_checker([clause("a")], [set()])
    assert all(s.precision == s.recall == 1.0 for s in report.by_kind)
    assert score_checker([], []).exact_accuracy == 1.0


def test_to_dict_is_json_ready() -> None:
    report = score_checker([clause("a", ("r1", V))], [{("r1", C)}])
    summary = report.to_dict()
    assert summary["clauses"] == 1
    assert summary["exact_accuracy"] == 0.0
    assert summary["by_kind"] == {
        "violation": {"precision": 1.0, "recall": 0.0, "correct": 0, "predicted": 0, "expected": 1},
        "compliant": {"precision": 0.0, "recall": 1.0, "correct": 0, "predicted": 1, "expected": 0},
        "review_needed": {
            "precision": 1.0,
            "recall": 1.0,
            "correct": 0,
            "predicted": 0,
            "expected": 0,
        },
    }
    assert summary["misses"] == [
        {"clause_id": "a", "expected": ["r1:violation"], "predicted": ["r1:compliant"]}
    ]


def test_needs_one_prediction_per_clause() -> None:
    with pytest.raises(InvalidDomainObjectError):
        score_checker([clause("a")], [])
