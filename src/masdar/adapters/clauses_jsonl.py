"""Read labeled contract clauses from a JSON Lines file."""

import json
from pathlib import Path

from masdar.domain.checker_quality import LabeledClause, parse_labeled_clause
from masdar.domain.errors import InvalidDomainObjectError, SourceFormatError


class JsonlLabeledClauseSource:
    """Labeled clauses (``_id``, ``text``, ``expected``), one JSON object per line."""

    def __init__(self, path: Path) -> None:
        """Read from ``path``."""
        self._path = path

    def load(self) -> tuple[LabeledClause, ...]:
        """Every labeled clause, in file order.

        Raises:
            SourceFormatError: If the file is missing or a line is not a valid clause.
        """
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError as error:
            raise SourceFormatError(f"{self._path} not found") from error
        clauses = []
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                clauses.append(parse_labeled_clause(json.loads(line)))
            except (json.JSONDecodeError, InvalidDomainObjectError) as error:
                raise SourceFormatError(f"{self._path}:{number}: {error}") from error
        return tuple(clauses)
