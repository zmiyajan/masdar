"""Port: where a built dataset is written."""

from collections.abc import Sequence
from typing import Protocol

from masdar.domain.dataset import DatasetReport
from masdar.domain.models import Article


class DatasetWriter(Protocol):
    """Persists the corpus and its report (e.g. BEIR files and a dataset card)."""

    def write(self, articles: Sequence[Article], report: DatasetReport) -> None:
        """Write ``articles`` (the corpus) together with ``report``."""
        ...
