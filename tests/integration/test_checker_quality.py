"""Quality gate: the contract checker must not get worse on the labeled clauses.

``data/gold/clauses.v1.jsonl`` holds contract and policy clauses with the
findings a careful reviewer expects. This test runs the Labor Law rules on each
clause (no splitting, no retrieval) and fails if a measured score falls below
what ADR-0010 records. Violation precision is held at 1.0: a wrong
"violation" on a real contract is the error this checker must never make.
An improvement passes; record it in the ADR in the same commit.
"""

import json
from pathlib import Path

import pytest

from masdar.domain.checker_quality import (
    CheckerQualityReport,
    LabeledClause,
    parse_labeled_clause,
    score_checker,
)
from masdar.domain.compliance import FindingKind, check_clause
from masdar.domain.labor_rules import LABOR_RULES

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUSES = REPO_ROOT / "data" / "gold" / "clauses.v1.jsonl"

# Recorded 2026-10-07 on 90 clauses (ADR-0010).
RECORDED = {
    FindingKind.VIOLATION: (1.0, 1.0),
    FindingKind.COMPLIANT: (1.0, 0.9412),
    FindingKind.REVIEW_NEEDED: (0.8462, 1.0),
}
RECORDED_EXACT_ACCURACY = 0.9667
TOLERANCE = 0.01


@pytest.fixture(scope="module")
def labeled() -> list[LabeledClause]:
    lines = CLAUSES.read_text(encoding="utf-8").splitlines()
    return [parse_labeled_clause(json.loads(line)) for line in lines if line.strip()]


@pytest.fixture(scope="module")
def report(labeled: list[LabeledClause]) -> CheckerQualityReport:
    predicted = [
        {(finding.rule_id, finding.kind) for finding in check_clause(clause.text, LABOR_RULES)}
        for clause in labeled
    ]
    return score_checker(labeled, predicted)


def test_labeled_set_is_well_formed(labeled: list[LabeledClause]) -> None:
    ids = [clause.clause_id for clause in labeled]
    assert ids == [f"cl-{n:03d}" for n in range(1, len(ids) + 1)]
    known = {rule.rule_id for rule in LABOR_RULES}
    assert {rule for clause in labeled for rule, _ in clause.expected} <= known
    assert len(labeled) == 90
    assert sum(1 for clause in labeled if not clause.expected) >= 10


def test_no_false_violations(report: CheckerQualityReport) -> None:
    assert report.score(FindingKind.VIOLATION).precision == 1.0, report.to_dict()["misses"]


@pytest.mark.parametrize("kind", list(FindingKind))
def test_precision_and_recall_do_not_regress(
    report: CheckerQualityReport, kind: FindingKind
) -> None:
    precision, recall = RECORDED[kind]
    score = report.score(kind)
    assert score.precision >= precision - TOLERANCE, report.to_dict()["misses"]
    assert score.recall >= recall - TOLERANCE, report.to_dict()["misses"]


def test_exact_clause_accuracy_does_not_regress(report: CheckerQualityReport) -> None:
    assert report.exact_accuracy >= RECORDED_EXACT_ACCURACY - TOLERANCE, report.to_dict()["misses"]
