"""Tests for parsing Arabic ordinal article headings."""

import pytest

from masdar.domain.errors import ArticleHeadingError
from masdar.domain.ordinals import ArticleNumber, parse_article_number


@pytest.mark.parametrize(
    ("heading", "expected"),
    [
        pytest.param("المادة الأولى :", ArticleNumber(1), id="first"),
        pytest.param("المادة العاشرة", ArticleNumber(10), id="tenth"),
        pytest.param("المادة الحادية عشرة", ArticleNumber(11), id="eleven-feminine"),
        pytest.param("المادة الثانية عشرة", ArticleNumber(12), id="twelve"),
        pytest.param("المادة العشرون", ArticleNumber(20), id="twenty"),
        pytest.param("المادة الخامسة والأربعون", ArticleNumber(45), id="tens-with-waw"),
        pytest.param("المادة المائة", ArticleNumber(100), id="hundred"),
        pytest.param("المادة الحادية بعد المائة", ArticleNumber(101), id="hundred-and-one"),
        pytest.param(
            "المادة الخامسة والأربعون بعد المائتين :", ArticleNumber(245), id="two-hundreds"
        ),
        pytest.param(
            "المادة الحادية والثمانون بعد المائتين: نفاذ النظام",
            ArticleNumber(281),
            id="title-after-colon",
        ),
        pytest.param("( التاسعة والسبعين مكرر )", ArticleNumber(79, bis=True), id="bis-genitive"),
        pytest.param(
            "(المادة الحادية والثلاثون بعد المائتين حالياً) (المادة الأربعون بعد المائتين سابقاً)",
            ArticleNumber(231),
            id="renumbered-currently-wins",
        ),
        pytest.param("المادة المئتين", ArticleNumber(200), id="hamza-less-spelling"),
    ],
)
def test_parses_published_headings(heading: str, expected: ArticleNumber) -> None:
    assert parse_article_number(heading) == expected


@pytest.mark.parametrize(
    "heading",
    [
        pytest.param("المادة", id="no-number"),
        pytest.param("المادة الكبيرة", id="unknown-word"),
        pytest.param("", id="empty"),
    ],
)
def test_rejects_headings_without_a_number(heading: str) -> None:
    with pytest.raises(ArticleHeadingError):
        parse_article_number(heading)


def test_bis_article_sorts_right_after_its_base() -> None:
    assert sorted([ArticleNumber(80), ArticleNumber(79, bis=True), ArticleNumber(79)]) == [
        ArticleNumber(79),
        ArticleNumber(79, bis=True),
        ArticleNumber(80),
    ]


@pytest.mark.parametrize(
    ("number", "slug"), [(ArticleNumber(12), "12"), (ArticleNumber(79, bis=True), "79-bis")]
)
def test_slug(number: ArticleNumber, slug: str) -> None:
    assert number.slug == slug
