"""Tests for dataset report arithmetic."""

from masdar.domain.amendments import ArticleStatus
from masdar.domain.dataset import DatasetReport, LawSummary, count_statuses
from masdar.domain.models import Article
from masdar.domain.ordinals import ArticleNumber


def summary(law_id: str, **counts: int) -> LawSummary:
    statuses = tuple((status, counts.get(status.value, 0)) for status in ArticleStatus)
    return LawSummary(law_id, law_id, "https://example.test", None, statuses, chunks=0)


def test_totals_per_law_and_per_status() -> None:
    report = DatasetReport(
        (summary("a", in_force=3, repealed=1), summary("b", amended=2, superseded=4))
    )
    assert report.laws[0].total == 4
    assert report.total() == 10
    assert report.total(ArticleStatus.SUPERSEDED) == 4
    assert report.laws[1].count(ArticleStatus.REVIEW_NEEDED) == 0


def test_count_statuses_lists_every_status_including_zeros() -> None:
    article = Article("l", "ن", ArticleNumber(1), "المادة الأولى", "نص")
    counts = dict(count_statuses([article, article]))
    assert counts[ArticleStatus.IN_FORCE] == 2
    assert set(counts) == set(ArticleStatus)
    assert counts[ArticleStatus.REPEALED] == 0
