"""Port: re-score a short list of candidates with a more expensive model."""

from collections.abc import Sequence
from typing import Protocol

from masdar.domain.models import Hit


class Reranker(Protocol):
    """Reorders retrieved candidates (e.g. a cross-encoder)."""

    @property
    def name(self) -> str:
        """Short identifier used in results and reports."""
        ...

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        """Return the best ``k`` of ``hits`` for ``query``, best first, ranks from 1."""
        ...
