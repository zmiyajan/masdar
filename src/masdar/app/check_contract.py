"""Use case: check a pasted contract or HR policy against the law in force.

Each clause gets two things: the related articles of the law in force (from
the same `SearchService` users search with), and, where it states a quantity
the Labor Law limits, a deterministic verdict with the article to cite. No
model or API is involved in the verdicts; see ADR-0010.
"""

from collections.abc import Collection, Sequence

from masdar.app.search import SearchService
from masdar.domain.checker_quality import CheckerQualityReport, LabeledClause, score_checker
from masdar.domain.compliance import (
    ClauseReport,
    ContractReport,
    Rule,
    check_clause,
    clause_query,
    split_clauses,
)
from masdar.domain.errors import InvalidDomainObjectError

DEFAULT_MAX_CHARS = 20_000
"""About ten pages of contract: enough for real documents, bounded for a public demo."""


class CheckContract:
    """Split a document into clauses, check each one, and attach related articles."""

    def __init__(
        self,
        search: SearchService,
        rules: Sequence[Rule],
        *,
        related_k: int = 3,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        """Create the use case.

        Args:
            search: Retrieves related articles for each clause.
            rules: The rules to apply (e.g. `masdar.domain.labor_rules.LABOR_RULES`).
            related_k: How many related articles to attach to each clause.
            max_chars: Longest document accepted.

        Raises:
            InvalidDomainObjectError: If ``related_k`` or ``max_chars`` is not positive.
        """
        if related_k < 1 or max_chars < 1:
            raise InvalidDomainObjectError("related_k and max_chars must be positive")
        self._search = search
        self._rules = tuple(rules)
        self._related_k = related_k
        self._max_chars = max_chars

    def run(self, text: str, laws: Collection[str] | None = None) -> ContractReport:
        """Check every clause of ``text``.

        Args:
            text: The contract or policy, as pasted.
            laws: Restrict related articles, and the rules applied, to these law
                ids; ``None`` means every law.

        Returns:
            One `ClauseReport` per clause, in document order.

        Raises:
            InvalidDomainObjectError: If the text is blank or longer than ``max_chars``.
        """
        if not text.strip():
            raise InvalidDomainObjectError("The document is empty")
        if len(text) > self._max_chars:
            raise InvalidDomainObjectError(
                f"The document is longer than {self._max_chars} characters"
            )
        rules = [rule for rule in self._rules if not laws or rule.law_id in laws]
        return ContractReport(
            tuple(
                ClauseReport(
                    clause,
                    check_clause(clause.text, rules),
                    tuple(self._search.search(clause_query(clause.text), self._related_k, laws)),
                )
                for clause in split_clauses(text)
            )
        )


def measure_checker(
    labeled: Sequence[LabeledClause], rules: Sequence[Rule]
) -> CheckerQualityReport:
    """Score the verdicts on labeled clauses (retrieval plays no part in a verdict).

    Args:
        labeled: Clauses with their expected ``(rule_id, kind)`` findings.
        rules: The rules to apply, as served.
    """
    predicted = [
        {(finding.rule.rule_id, finding.kind) for finding in check_clause(clause.text, rules)}
        for clause in labeled
    ]
    return score_checker(labeled, predicted)
