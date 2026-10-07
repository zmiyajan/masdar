"""Measure the contract checker on clauses labeled by a person.

Each labeled clause lists the findings a careful reviewer expects: which rule
fires and with which verdict. A predicted finding counts as correct only if
both the rule and the verdict match. Precision and recall are reported per
verdict, because the verdicts carry different risks: a wrong ``violation``
misleads a user about a real contract, while a missed one only leaves the
clause to the related articles shown beside it.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from masdar.domain.compliance import FindingKind
from masdar.domain.errors import InvalidDomainObjectError

ExpectedFinding = tuple[str, FindingKind]
"""``(rule_id, kind)``: one finding as the labels and the scorer see it."""


@dataclass(frozen=True, slots=True)
class LabeledClause:
    """One clause with the findings a person expects.

    Attributes:
        clause_id: Stable id, e.g. ``"cl-001"``.
        text: The clause.
        expected: Expected findings; empty when no rule should fire.
        note: Why the label is what it is.
    """

    clause_id: str
    text: str
    expected: frozenset[ExpectedFinding]
    note: str = ""

    def __post_init__(self) -> None:
        """A clause without an id or text cannot be scored."""
        if not self.clause_id.strip() or not self.text.strip():
            raise InvalidDomainObjectError("LabeledClause needs an id and a text")


def parse_labeled_clause(record: Mapping[str, object]) -> LabeledClause:
    """Build a `LabeledClause` from one decoded JSON line.

    Raises:
        InvalidDomainObjectError: If a field is missing or has the wrong type.
    """
    clause_id, text, note = record.get("_id"), record.get("text"), record.get("note", "")
    expected = record.get("expected")
    if not isinstance(clause_id, str) or not isinstance(text, str) or not isinstance(note, str):
        raise InvalidDomainObjectError(f"Bad labeled clause: {record!r}")
    if not isinstance(expected, list):
        raise InvalidDomainObjectError(f"{clause_id}: 'expected' must be a list")
    return LabeledClause(
        clause_id, text, frozenset(_parse_finding(clause_id, e) for e in expected), note
    )


def _parse_finding(clause_id: str, item: object) -> ExpectedFinding:
    if not isinstance(item, dict):
        raise InvalidDomainObjectError(f"{clause_id}: each expected finding must be an object")
    rule_id, kind = item.get("rule_id"), item.get("kind")
    if not isinstance(rule_id, str) or kind not in set(FindingKind):
        raise InvalidDomainObjectError(f"{clause_id}: bad expected finding {item!r}")
    return rule_id, FindingKind(str(kind))


@dataclass(frozen=True, slots=True)
class KindScore:
    """Precision and recall of one verdict.

    Attributes:
        kind: The verdict.
        correct: Predicted findings of this kind that were expected.
        predicted: Findings of this kind the checker returned.
        expected: Findings of this kind the labels contain.
    """

    kind: FindingKind
    correct: int
    predicted: int
    expected: int

    @property
    def precision(self) -> float:
        """Share of predictions that were right; 1.0 when nothing was predicted."""
        return self.correct / self.predicted if self.predicted else 1.0

    @property
    def recall(self) -> float:
        """Share of expected findings that were found; 1.0 when none were expected."""
        return self.correct / self.expected if self.expected else 1.0


@dataclass(frozen=True, slots=True)
class ClauseMiss:
    """A clause whose predicted findings differ from the labels."""

    clause_id: str
    expected: frozenset[ExpectedFinding]
    predicted: frozenset[ExpectedFinding]


@dataclass(frozen=True, slots=True)
class CheckerQualityReport:
    """How well the checker agrees with the labels.

    Attributes:
        clauses: Number of labeled clauses.
        exact: Clauses whose predicted findings equal the expected ones exactly.
        by_kind: Precision and recall per verdict.
        misses: Every clause that was not exact, for inspection.
    """

    clauses: int
    exact: int
    by_kind: tuple[KindScore, ...]
    misses: tuple[ClauseMiss, ...]

    @property
    def exact_accuracy(self) -> float:
        """Share of clauses with exactly the expected findings."""
        return self.exact / self.clauses if self.clauses else 1.0

    def score(self, kind: FindingKind) -> KindScore:
        """The score of one verdict."""
        return next(score for score in self.by_kind if score.kind is kind)

    def to_dict(self) -> dict[str, object]:
        """A JSON-ready summary, rounded to four decimals."""
        return {
            "clauses": self.clauses,
            "exact_accuracy": round(self.exact_accuracy, 4),
            "by_kind": {
                score.kind.value: {
                    "precision": round(score.precision, 4),
                    "recall": round(score.recall, 4),
                    "correct": score.correct,
                    "predicted": score.predicted,
                    "expected": score.expected,
                }
                for score in self.by_kind
            },
            "misses": [
                {
                    "clause_id": miss.clause_id,
                    "expected": sorted(f"{rule}:{kind}" for rule, kind in miss.expected),
                    "predicted": sorted(f"{rule}:{kind}" for rule, kind in miss.predicted),
                }
                for miss in self.misses
            ],
        }


def score_checker(
    labeled: Sequence[LabeledClause], predicted: Sequence[Collection[ExpectedFinding]]
) -> CheckerQualityReport:
    """Compare predicted findings with the labels, clause by clause.

    Args:
        labeled: The labeled clauses.
        predicted: For each labeled clause, in the same order, the
            ``(rule_id, kind)`` pairs the checker returned.

    Raises:
        InvalidDomainObjectError: If the two sequences differ in length.

    Example:
        >>> clause = LabeledClause("c1", "نص", frozenset({("r", FindingKind.VIOLATION)}))
        >>> score_checker([clause], [{("r", FindingKind.VIOLATION)}]).exact_accuracy
        1.0
    """
    if len(labeled) != len(predicted):
        raise InvalidDomainObjectError("One prediction per labeled clause is required")
    correct = dict.fromkeys(FindingKind, 0)
    made = dict.fromkeys(FindingKind, 0)
    wanted = dict.fromkeys(FindingKind, 0)
    misses: list[ClauseMiss] = []
    for clause, found in zip(labeled, predicted, strict=True):
        got = frozenset(found)
        for _, kind in got:
            made[kind] += 1
        for _, kind in clause.expected:
            wanted[kind] += 1
        for _, kind in got & clause.expected:
            correct[kind] += 1
        if got != clause.expected:
            misses.append(ClauseMiss(clause.clause_id, clause.expected, got))
    by_kind = tuple(KindScore(k, correct[k], made[k], wanted[k]) for k in FindingKind)
    return CheckerQualityReport(len(labeled), len(labeled) - len(misses), by_kind, tuple(misses))
