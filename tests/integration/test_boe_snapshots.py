"""Golden tests on the committed snapshots of the real law pages.

These pin what Masdar extracts from the official sources. If the parser, the
amendment rules or the snapshots change, a failure here shows exactly which
law and which article moved, so the change is reviewed rather than silent.
"""

import re
from pathlib import Path

import httpx
import pytest

from masdar.adapters.boe.client import BoeClient
from masdar.adapters.boe.source import BoeLawSource
from masdar.domain.amendments import ArticleStatus
from masdar.domain.arabic import ArabicNormalizer, normalize_arabic
from masdar.domain.articles import build_articles, duplicate_current_numbers
from masdar.domain.chunking import chunk_article
from masdar.domain.models import Article
from masdar.domain.ordinals import ArticleNumber

S = ArticleStatus


@pytest.fixture(scope="module")
def laws(snapshot_dir: Path) -> dict[str, list[Article]]:
    def no_network(_: httpx.Request) -> httpx.Response:
        raise AssertionError("tests must not use the network")

    client = BoeClient(
        httpx.Client(transport=httpx.MockTransport(no_network)),
        snapshot_dir,
        crawl_delay=10.0,
        offline=True,
    )
    source = BoeLawSource(client, snapshot_dir)
    return {law_id: build_articles(source.load(law_id)) for law_id in source.law_ids()}


def article(articles: list[Article], number: ArticleNumber, *, current: bool = True) -> Article:
    [match] = [a for a in articles if a.number == number and a.is_current == current]
    return match


@pytest.mark.parametrize(
    ("law_id", "expected"),
    [
        (
            "labor-law",
            {S.IN_FORCE: 140, S.AMENDED: 53, S.REVIEW_NEEDED: 18, S.REPEALED: 29, S.SUPERSEDED: 12},
        ),
        (
            "pdpl",
            {S.IN_FORCE: 19, S.AMENDED: 12, S.REVIEW_NEEDED: 11, S.REPEALED: 1, S.SUPERSEDED: 0},
        ),
        (
            "companies-law",
            {S.IN_FORCE: 281, S.AMENDED: 0, S.REVIEW_NEEDED: 0, S.REPEALED: 0, S.SUPERSEDED: 0},
        ),
    ],
)
def test_status_counts_per_law(
    laws: dict[str, list[Article]], law_id: str, expected: dict[ArticleStatus, int]
) -> None:
    actual = {status: sum(a.status is status for a in laws[law_id]) for status in ArticleStatus}
    assert actual == expected


@pytest.mark.parametrize("law_id", ["labor-law", "pdpl", "companies-law"])
def test_current_article_numbers_are_unique(laws: dict[str, list[Article]], law_id: str) -> None:
    assert duplicate_current_numbers(laws[law_id]) == []


def test_labor_law_current_numbering_is_fully_explained(laws: dict[str, list[Article]]) -> None:
    current = {a.number for a in laws["labor-law"] if a.is_current}
    gone = {a.number for a in laws["labor-law"] if not a.is_current}
    # Every number from 1 to 245 is either current or accounted for as
    # repealed/superseded; renumbered 240 and 242 now live at 231 and 232.
    unexplained = {ArticleNumber(n) for n in range(1, 246)} - current - gone
    assert unexplained == {ArticleNumber(240), ArticleNumber(242)}
    assert {
        ArticleNumber(11, bis=True),
        ArticleNumber(79, bis=True),
        ArticleNumber(229, bis=True),
    } <= current


def test_amended_article_carries_the_1446_wording(laws: dict[str, list[Article]]) -> None:
    seventh = article(laws["labor-law"], ArticleNumber(7))
    assert seventh.status is ArticleStatus.AMENDED
    assert seventh.text.startswith("1- يستثنى من تطبيق أحكام هذا النظام")
    assert seventh.original_text != seventh.text


def test_article_added_only_inside_a_note_exists(laws: dict[str, list[Article]]) -> None:
    eleven_bis = article(laws["labor-law"], ArticleNumber(11, bis=True))
    assert eleven_bis.heading == "المادة الحادية عشرة مكرر"
    assert "تحسين أداء سوق العمل" in eleven_bis.text


def test_bis_article_on_resignation(laws: dict[str, list[Article]]) -> None:
    resignation = article(laws["labor-law"], ArticleNumber(79, bis=True))
    assert "طلب الاستقالة" in resignation.text
    assert "(ثلاثون) يوماً" in resignation.text


def test_consolidated_and_renumbered_articles(laws: dict[str, list[Article]]) -> None:
    labor = laws["labor-law"]
    assert article(labor, ArticleNumber(14), current=False).status is ArticleStatus.SUPERSEDED
    old_231 = article(labor, ArticleNumber(231), current=False)
    new_231 = article(labor, ArticleNumber(231))
    assert old_231.status is ArticleStatus.SUPERSEDED
    assert new_231.text.startswith("يلزم مرتكب المخالفة")  # formerly article 240


def test_repealed_part_fourteen(laws: dict[str, list[Article]]) -> None:
    repealed = article(laws["labor-law"], ArticleNumber(210), current=False)
    assert repealed.status is ArticleStatus.REPEALED
    assert repealed.part is not None
    assert "الرابع عشر" in repealed.part


def test_partially_amended_definitions_are_flagged_with_their_note(
    laws: dict[str, list[Article]],
) -> None:
    definitions = article(laws["labor-law"], ArticleNumber(2))
    assert definitions.status is ArticleStatus.REVIEW_NEEDED
    assert any("ذكراً أو أنثى" in a.note for a in definitions.amendments)


def test_companies_law_article_titles(laws: dict[str, list[Article]]) -> None:
    first = article(laws["companies-law"], ArticleNumber(1))
    assert first.title == "التعريفات"
    assert first.heading == "المادة الأولى"


# Phrases that belong to amendment notes, never to the text of a law.
NOTE_LANGUAGE = re.compile(r"بالنص الاتي|عدلت الفقره|تعديل الفقره|بموجب المرسوم|لتكون بالنص")


@pytest.mark.parametrize("law_id", ["labor-law", "pdpl", "companies-law"])
def test_amended_text_never_contains_amendment_note_language(
    laws: dict[str, list[Article]], law_id: str
) -> None:
    leaks = [
        a.article_id
        for a in laws[law_id]
        if a.status is ArticleStatus.AMENDED and NOTE_LANGUAGE.search(normalize_arabic(a.text))
    ]
    assert leaks == []


@pytest.mark.parametrize(
    ("law_id", "number"), [("labor-law", ArticleNumber(22)), ("pdpl", ArticleNumber(13))]
)
def test_notes_listing_several_edits_are_not_applied_as_a_full_text(
    laws: dict[str, list[Article]], law_id: str, number: ArticleNumber
) -> None:
    assert article(laws[law_id], number).status is ArticleStatus.REVIEW_NEEDED


def test_dual_consolidation_supersedes_the_folded_article(laws: dict[str, list[Article]]) -> None:
    labor = laws["labor-law"]
    assert article(labor, ArticleNumber(151)).status is ArticleStatus.AMENDED
    assert article(labor, ArticleNumber(152), current=False).status is ArticleStatus.SUPERSEDED


def test_article_added_with_tartib_wording_exists(laws: dict[str, list[Article]]) -> None:
    added = article(laws["labor-law"], ArticleNumber(131, bis=True))
    assert added.heading.startswith("المادة الحادية والثلاثين بعد المائة مكرر")
    assert article(laws["labor-law"], ArticleNumber(131)).status is ArticleStatus.IN_FORCE


@pytest.mark.parametrize("law_id", ["labor-law", "pdpl", "companies-law"])
def test_every_amendment_note_is_dated(laws: dict[str, list[Article]], law_id: str) -> None:
    undated = [a.article_id for a in laws[law_id] for am in a.amendments if am.issued is None]
    assert undated == []


@pytest.mark.parametrize("law_id", ["labor-law", "pdpl", "companies-law"])
def test_chunking_the_real_corpus_loses_no_words(
    laws: dict[str, list[Article]], law_id: str
) -> None:
    normalizer = ArabicNormalizer()
    for current in (a for a in laws[law_id] if a.is_current):
        chunks = chunk_article(current, normalizer)
        assert " ".join(c.text for c in chunks).split() == current.text.split()
