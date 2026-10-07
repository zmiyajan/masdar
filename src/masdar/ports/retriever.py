"""Port: anything that turns a question into ranked chunks."""

from typing import Protocol

from masdar.domain.models import Hit


class Retriever(Protocol):
    """A search component: BM25, dense, hybrid, and so on.

    Implementations receive the raw user question and apply their own
    normalization, so each retriever can be evaluated exactly as it runs.
    """

    @property
    def name(self) -> str:
        """Short identifier used in results and reports, e.g. ``"bm25"``."""
        ...

    def search(self, query: str, k: int) -> list[Hit]:
        """Return up to ``k`` chunk hits, best first, with ranks starting at 1."""
        ...
