"""Read the out-of-scope question set from a JSON Lines file.

Questions the corpus does not answer; an answer service should refuse them.
File format, one question per line::

    {"_id": "oos-001", "text": "...", "topic": "traffic", "style": "formal"}
"""

import json
from pathlib import Path
from typing import Any

from masdar.domain.answer import OutOfScopeQuestion
from masdar.domain.errors import InvalidDomainObjectError, SourceFormatError
from masdar.domain.gold import QueryStyle


class JsonlOutOfScopeSource:
    """Out-of-scope questions stored as ``out_of_scope.<version>.jsonl``."""

    def __init__(self, path: Path) -> None:
        """Read questions from ``path``, e.g. ``data/gold/out_of_scope.v1.jsonl``."""
        self._path = path

    def load(self) -> tuple[OutOfScopeQuestion, ...]:
        """Parse every line.

        Raises:
            SourceFormatError: If the file is missing, a line is not valid
                JSON, a field is missing or invalid, or an id repeats.
        """
        if not self._path.exists():
            raise SourceFormatError(f"Out-of-scope set not found: {self._path}")
        questions: list[OutOfScopeQuestion] = []
        seen: set[str] = set()
        lines = self._path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            question = self._parse(line, number)
            if question.query_id in seen:
                raise SourceFormatError(f"{self._path}:{number}: duplicate id {question.query_id}")
            seen.add(question.query_id)
            questions.append(question)
        return tuple(questions)

    def _parse(self, line: str, number: int) -> OutOfScopeQuestion:
        where = f"{self._path}:{number}"
        try:
            record: dict[str, Any] = json.loads(line)
            return OutOfScopeQuestion(
                query_id=str(record["_id"]),
                text=str(record["text"]),
                topic=str(record["topic"]),
                style=QueryStyle(record["style"]),
            )
        # JSONDecodeError and InvalidDomainObjectError are ValueErrors too, so
        # they are caught first to keep their specific messages.
        except json.JSONDecodeError as error:
            raise SourceFormatError(f"{where}: invalid JSON: {error}") from error
        except InvalidDomainObjectError as error:
            raise SourceFormatError(f"{where}: {error}") from error
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise SourceFormatError(f"{where}: invalid record: {error!r}") from error
