"""Port: where published laws come from."""

from typing import Protocol

from masdar.domain.articles import PublishedLaw


class LawSource(Protocol):
    """Provides laws as published, before any legal processing."""

    def law_ids(self) -> tuple[str, ...]:
        """Slugs of every law this source can provide."""
        ...

    def load(self, law_id: str) -> PublishedLaw:
        """Return one law as published."""
        ...
