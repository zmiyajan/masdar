"""What a dataset build produced: per-law counts used by the dataset card."""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass

from masdar.domain.amendments import AmendmentKind, ArticleStatus
from masdar.domain.gold import GoldQuery, QueryStyle
from masdar.domain.models import CURRENT_STATUSES, Article

DATASET_NAME = "Saudi Regulations Arabic Retrieval Benchmark"
DATASET_VERSION = "1.0.0"


@dataclass(frozen=True, slots=True)
class LawSummary:
    """Counts for one law in the dataset.

    Attributes:
        law_id: Masdar's slug for the law.
        title: Official title.
        source_url: Where the text was fetched from.
        retrieved_on: ISO date of the source snapshot, when known.
        status_counts: Articles per `ArticleStatus`, in enum order.
        chunks: Number of chunks the current articles produce.
        amendment_counts: Parsed amendment notes per `AmendmentKind`.
        outdated_on_portal: Current articles whose text in force differs from
            the wording the portal displays as the article body.
    """

    law_id: str
    title: str
    source_url: str
    retrieved_on: str | None
    status_counts: tuple[tuple[ArticleStatus, int], ...]
    chunks: int
    amendment_counts: tuple[tuple[AmendmentKind, int], ...] = ()
    outdated_on_portal: int = 0

    @property
    def total(self) -> int:
        """All articles, including repealed and superseded ones."""
        return sum(count for _, count in self.status_counts)

    @property
    def current(self) -> int:
        """Articles that are current law (see `masdar.domain.models.CURRENT_STATUSES`)."""
        return sum(self.count(status) for status in CURRENT_STATUSES)

    def count(self, status: ArticleStatus) -> int:
        """Number of articles with ``status``."""
        return dict(self.status_counts).get(status, 0)


@dataclass(frozen=True, slots=True)
class DatasetReport:
    """Summary of a dataset build."""

    laws: tuple[LawSummary, ...]
    name: str = DATASET_NAME
    version: str = DATASET_VERSION
    gold_version: str | None = None
    query_styles: tuple[tuple[QueryStyle, int], ...] = ()

    @property
    def queries(self) -> int:
        """Number of gold questions in the dataset."""
        return sum(count for _, count in self.query_styles)

    def total(self, status: ArticleStatus | None = None) -> int:
        """Articles across all laws, optionally only those with ``status``."""
        if status is None:
            return sum(law.total for law in self.laws)
        return sum(law.count(status) for law in self.laws)


def count_statuses(articles: Sequence[Article]) -> tuple[tuple[ArticleStatus, int], ...]:
    """Articles per status, listing every status (zeros included) in enum order."""
    counts = Counter(article.status for article in articles)
    return tuple((status, counts.get(status, 0)) for status in ArticleStatus)


def count_amendment_kinds(articles: Sequence[Article]) -> tuple[tuple[AmendmentKind, int], ...]:
    """Amendment notes per kind across ``articles``, every kind listed."""
    counts = Counter(amendment.kind for article in articles for amendment in article.amendments)
    return tuple((kind, counts.get(kind, 0)) for kind in AmendmentKind)


def count_outdated_on_portal(articles: Sequence[Article]) -> int:
    """Current articles whose text in force is not the body the portal displays.

    This is the measurable size of the problem in ADR-0005: indexing the
    portal's article bodies as published would serve these articles outdated.
    """
    return sum(
        1
        for article in articles
        if article.is_current
        and article.original_text is not None
        and article.text != article.original_text
    )


def count_query_styles(queries: Sequence[GoldQuery]) -> tuple[tuple[QueryStyle, int], ...]:
    """Gold questions per wording style, every style listed."""
    counts = Counter(query.style for query in queries)
    return tuple((style, counts.get(style, 0)) for style in QueryStyle)
