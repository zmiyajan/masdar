"""Integration tests for the BuildDataset use case, wired with in-memory fakes."""

from collections.abc import Sequence

import pytest

from masdar.app.build_dataset import BuildDataset
from masdar.domain.amendments import ArticleStatus
from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.articles import ArticleSource, PublishedLaw
from masdar.domain.chunking import ChunkingOptions
from masdar.domain.dataset import DatasetReport
from masdar.domain.errors import DataIntegrityError
from masdar.domain.models import Article

CONSOLIDATE = (
    "تم تعديل أحكام المواد (الأولى) و(الثانية)؛ وإعادة صياغتها لتكون في مادة واحدة بموجب "
    "المرسوم الملكي رقم ( م/ 46) وتاريخ 5 / 6 / 1436 هـ ؛ "
    'على النحو الآتي : "المادة الأولى : نص موحد"'
)


class FakeSource:
    def __init__(self, *laws: PublishedLaw) -> None:
        self._laws = {law.law_id: law for law in laws}

    def law_ids(self) -> tuple[str, ...]:
        return tuple(self._laws)

    def load(self, law_id: str) -> PublishedLaw:
        return self._laws[law_id]


class MemoryWriter:
    def __init__(self) -> None:
        self.articles: list[Article] = []
        self.report: DatasetReport | None = None

    def write(self, articles: Sequence[Article], report: DatasetReport) -> None:
        self.articles = list(articles)
        self.report = report


def published(law_id: str, *sources: ArticleSource) -> PublishedLaw:
    return PublishedLaw(
        law_id, f"نظام {law_id}", f"https://example.test/{law_id}", sources, "2026-10-07"
    )


def run(*laws: PublishedLaw, law_ids: list[str] | None = None) -> MemoryWriter:
    writer = MemoryWriter()
    BuildDataset(FakeSource(*laws), writer, ArabicNormalizer(), ChunkingOptions()).run(law_ids)
    return writer


def test_builds_every_law_and_reports_counts() -> None:
    writer = run(
        published("a", ArticleSource("المادة الأولى", "نص أ")),
        published(
            "b", ArticleSource("المادة الأولى", "نص ب"), ArticleSource("المادة الثانية", "نص")
        ),
    )
    assert writer.report is not None
    assert [law.law_id for law in writer.report.laws] == ["a", "b"]
    assert [law.total for law in writer.report.laws] == [1, 2]
    assert writer.report.laws[1].chunks == 2
    assert writer.report.laws[0].retrieved_on == "2026-10-07"


def test_consolidation_passes_current_and_superseded_articles_to_the_writer() -> None:
    writer = run(
        published(
            "a",
            ArticleSource("المادة الأولى", "قديم 1", (CONSOLIDATE,)),
            ArticleSource("المادة الثانية", "قديم 2", (CONSOLIDATE,)),
        )
    )
    assert writer.report is not None
    assert writer.report.total(ArticleStatus.SUPERSEDED) == 1
    assert writer.report.laws[0].current == 1
    assert writer.report.laws[0].outdated_on_portal == 1
    statuses = {a.article_id: a.status for a in writer.articles}
    assert statuses == {"a:1": ArticleStatus.AMENDED, "a:2": ArticleStatus.SUPERSEDED}
    assert writer.articles[0].text == "نص موحد"


def test_can_build_a_subset_of_laws() -> None:
    writer = run(
        published("a", ArticleSource("المادة الأولى", "نص")),
        published("b", ArticleSource("المادة الأولى", "نص")),
        law_ids=["b"],
    )
    assert {a.law_id for a in writer.articles} == {"b"}


def test_refuses_to_publish_ambiguous_numbering() -> None:
    with pytest.raises(DataIntegrityError, match="share number"):
        run(
            published("a", ArticleSource("المادة الأولى", "أ"), ArticleSource("المادة الأولى", "ب"))
        )
