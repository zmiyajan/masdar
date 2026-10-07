"""Use case: build the corpus from published laws and write it as a dataset."""

from collections.abc import Sequence

from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.articles import build_articles, duplicate_current_numbers
from masdar.domain.chunking import ChunkingOptions, chunk_article
from masdar.domain.dataset import (
    DatasetReport,
    LawSummary,
    count_amendment_kinds,
    count_outdated_on_portal,
    count_statuses,
)
from masdar.domain.errors import DataIntegrityError
from masdar.domain.models import Article
from masdar.ports.dataset_writer import DatasetWriter
from masdar.ports.law_source import LawSource


class BuildDataset:
    """Load every law, resolve amendments, validate, and write the corpus."""

    def __init__(
        self,
        source: LawSource,
        writer: DatasetWriter,
        normalizer: ArabicNormalizer,
        chunking: ChunkingOptions,
    ) -> None:
        """Wire the use case to its collaborators (see `masdar.container`)."""
        self._source = source
        self._writer = writer
        self._normalizer = normalizer
        self._chunking = chunking

    def run(self, law_ids: Sequence[str] | None = None) -> DatasetReport:
        """Build and write the dataset.

        Args:
            law_ids: Laws to include; defaults to every law the source offers.

        Returns:
            Per-law counts, also written into the dataset card.

        Raises:
            DataIntegrityError: If two current articles of a law share a number,
                which would make citations ambiguous.
        """
        corpus: list[Article] = []
        summaries: list[LawSummary] = []
        for law_id in law_ids or self._source.law_ids():
            published = self._source.load(law_id)
            articles = build_articles(published)
            _check_integrity(law_id, articles)
            current = [article for article in articles if article.is_current]
            chunks = sum(len(chunk_article(a, self._normalizer, self._chunking)) for a in current)
            summaries.append(
                LawSummary(
                    law_id=law_id,
                    title=published.title,
                    source_url=published.source_url,
                    retrieved_on=published.retrieved_on,
                    status_counts=count_statuses(articles),
                    chunks=chunks,
                    amendment_counts=count_amendment_kinds(articles),
                    outdated_on_portal=count_outdated_on_portal(articles),
                )
            )
            corpus += articles

        report = DatasetReport(tuple(summaries))
        self._writer.write(corpus, report)
        return report


def _check_integrity(law_id: str, articles: Sequence[Article]) -> None:
    duplicates = duplicate_current_numbers(articles)
    if duplicates:
        numbers = ", ".join(number.slug for number in duplicates)
        raise DataIntegrityError(f"{law_id}: several current articles share number(s) {numbers}")
