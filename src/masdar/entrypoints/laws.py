"""Read the per-law summary that ``make dataset`` writes to ``stats.json``.

The API and the MCP server show which laws are searchable, how many articles
each has and when its snapshot was taken. That summary already exists as a
build artifact, so it is read here instead of being recomputed at startup.
"""

from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict


class LawSummary(BaseModel):
    """One searchable law, as published by the dataset build.

    Attributes:
        law_id: Stable slug, e.g. ``"labor-law"``.
        title: Official Arabic title.
        source_url: The law's page on the official portal.
        retrieved_on: The day the source snapshot was taken.
        articles: Every article, including repealed and superseded ones.
        current: Articles in force (what search covers).
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    law_id: str
    title: str
    source_url: str
    retrieved_on: date
    articles: int
    current: int


class _StatsFile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    laws: tuple[LawSummary, ...]


def load_law_summaries(stats_path: Path) -> tuple[LawSummary, ...]:
    """Parse ``stats.json`` into law summaries, in the file's order.

    Args:
        stats_path: Path to the dataset's ``stats.json``.

    Raises:
        FileNotFoundError: If the file is missing (the dataset was never built).
        pydantic.ValidationError: If the file does not match the expected schema.
    """
    return _StatsFile.model_validate_json(stats_path.read_text(encoding="utf-8")).laws
