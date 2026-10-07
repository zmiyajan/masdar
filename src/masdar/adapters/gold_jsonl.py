"""Read the gold question set from a JSON Lines file (implements `GoldSource`).

File format, one question per line::

    {"_id": "q001", "text": "...", "relevant": {"labor-law:53": 2}, "topic": "probation",
     "style": "formal"}
"""

import json
import re
from pathlib import Path
from typing import Any

from masdar.domain.errors import InvalidDomainObjectError, SourceFormatError
from masdar.domain.gold import GoldQuery, QueryStyle

_VERSION = re.compile(r"\.(v\d+)\.jsonl$")


class JsonlGoldSource:
    """Gold questions stored as ``queries.<version>.jsonl``."""

    def __init__(self, path: Path) -> None:
        """Read questions from ``path``, e.g. ``data/gold/queries.v1.jsonl``."""
        self._path = path

    @property
    def version(self) -> str:
        """The version in the file name (``v1``), or ``"unversioned"``."""
        match = _VERSION.search(self._path.name)
        return match.group(1) if match else "unversioned"

    def load(self) -> tuple[GoldQuery, ...]:
        """Parse every line.

        Raises:
            SourceFormatError: If the file is missing, a line is not valid
                JSON, a field is missing, or an id repeats.
        """
        if not self._path.exists():
            raise SourceFormatError(f"Gold set not found: {self._path}")
        queries: list[GoldQuery] = []
        seen: set[str] = set()
        lines = self._path.read_text(encoding="utf-8").splitlines()
        for number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            query = self._parse(line, number)
            if query.query_id in seen:
                raise SourceFormatError(f"{self._path}:{number}: duplicate id {query.query_id}")
            seen.add(query.query_id)
            queries.append(query)
        return tuple(queries)

    def _parse(self, line: str, number: int) -> GoldQuery:
        where = f"{self._path}:{number}"
        try:
            record: dict[str, Any] = json.loads(line)
            relevant = record["relevant"]
            return GoldQuery(
                query_id=str(record["_id"]),
                text=str(record["text"]),
                relevant=tuple((str(k), int(v)) for k, v in relevant.items()),
                topic=str(record["topic"]),
                style=QueryStyle(record["style"]),
            )
        # Order matters: JSONDecodeError and InvalidDomainObjectError are both
        # ValueErrors, so the specific handlers must come before the generic one.
        except json.JSONDecodeError as error:
            raise SourceFormatError(f"{where}: invalid JSON: {error}") from error
        except InvalidDomainObjectError as error:
            raise SourceFormatError(f"{where}: {error}") from error
        except (KeyError, AttributeError, TypeError, ValueError) as error:
            raise SourceFormatError(f"{where}: invalid gold record: {error!r}") from error
