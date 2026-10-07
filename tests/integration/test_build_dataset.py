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
from masdar.domain.gold import GoldQuery, QueryStyle
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
        self.queries: list[GoldQuery] = []

    def write(
        self,
        articles: Sequence[Article],
        report: DatasetReport,
        queries: Sequence[GoldQuery] = (),
    ) -> None:
        self.articles = list(articles)
        self.report = report
        self.queries = list(queries)


def published(law_id: str, *sources: ArticleSource) -> PublishedLaw:
    return PublishedLaw(
        law_id, f"نظام {law_id}", f"https://example.test/{law_id}", sources, "2026-10-07"
    )


class FakeGold:
    version = "v-test"

    def __init__(self, *queries: GoldQuery) -> None:
        self._queries = queries

    def load(self) -> tuple[GoldQuery, ...]:
        return self._queries


def gold(query_id: str, *article_ids: str) -> GoldQuery:
    relevant = tuple((article_id, 2) for article_id in article_ids)
    return GoldQuery(query_id, "سؤال", relevant, "topic", QueryStyle.FORMAL)


def run(
    *laws: PublishedLaw, law_ids: list[str] | None = None, gold_set: FakeGold | None = None
) -> MemoryWriter:
    writer = MemoryWriter()
    use_case = BuildDataset(
        FakeSource(*laws), writer, ArabicNormalizer(), ChunkingOptions(), gold=gold_set
    )
    use_case.run(law_ids)
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


def test_gold_questions_are_passed_to_the_writer_and_reported() -> None:
    writer = run(
        published("a", ArticleSource("المادة الأولى", "نص")), gold_set=FakeGold(gold("q1", "a:1"))
    )
    assert [q.query_id for q in writer.queries] == ["q1"]
    assert writer.report is not None
    assert (writer.report.gold_version, writer.report.queries) == ("v-test", 1)


def test_gold_question_citing_a_missing_article_stops_the_build() -> None:
    with pytest.raises(DataIntegrityError, match="q1 -> a:9"):
        run(
            published("a", ArticleSource("المادة الأولى", "نص")),
            gold_set=FakeGold(gold("q1", "a:9")),
        )


def test_gold_questions_about_laws_not_built_are_left_out() -> None:
    writer = run(
        published("a", ArticleSource("المادة الأولى", "نص")),
        published("b", ArticleSource("المادة الأولى", "نص")),
        law_ids=["a"],
        gold_set=FakeGold(gold("q1", "a:1"), gold("q2", "b:1")),
    )
    assert [q.query_id for q in writer.queries] == ["q1"]
