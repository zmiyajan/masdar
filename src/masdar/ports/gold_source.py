"""Port: where gold questions come from."""

from typing import Protocol

from masdar.domain.gold import GoldQuery


class GoldSource(Protocol):
    """Provides the gold question set."""

    @property
    def version(self) -> str:
        """Version label of the gold set, e.g. ``"v1"``."""
        ...

    def load(self) -> tuple[GoldQuery, ...]:
        """Return every gold question."""
        ...
