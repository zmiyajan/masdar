"""Tests for building articles from published blocks."""

from collections.abc import Sequence

from masdar.domain.amendments import ArticleStatus
from masdar.domain.articles import (
    ArticleSource,
    PublishedLaw,
    article_title,
    build_articles,
    clean_heading,
    duplicate_current_numbers,
)
from masdar.domain.models import Article
from masdar.domain.ordinals import ArticleNumber

ADD_11_BIS = (
    "تم إضافة مادة تحمل الرقم (الحادية عشرة مكرر) بموجب المرسوم الملكي رقم ( م/ 46) "
    'وتاريخ 5 / 6 / 1436 هـ ؛ بالنص الآتي : "للوزير أن يتخذ الإجراءات".'
)
SELF_ADDED_BODY = (
    "- اُضيفت هذه المادة بموجب المرسوم الملكي رقم (م/44) وتاريخ 1446/2/8هـ، وتكون بالنص "
    'الآتي: "يُعد طلب الاستقالة مقبولاً."'
)


def law(*sources: ArticleSource) -> PublishedLaw:
    return PublishedLaw("labor-law", "نظام العمل", "https://example.test/labor", sources)


def by_number(articles: Sequence[Article], number: ArticleNumber) -> list[Article]:
    return [a for a in articles if a.number == number]


def test_builds_plain_article_with_structure() -> None:
    [article] = build_articles(
        law(ArticleSource("المادة الأولى :", "يسمى هذا النظام.", (), "الباب الأول", "الفصل الأول"))
    )
    assert article.number == ArticleNumber(1)
    assert article.heading == "المادة الأولى"
    assert article.status is ArticleStatus.IN_FORCE
    assert (article.part, article.chapter) == ("الباب الأول", "الفصل الأول")
    assert article.original_text == article.text == "يسمى هذا النظام."


def test_article_that_exists_only_inside_another_articles_note_is_created() -> None:
    articles = build_articles(law(ArticleSource("المادة الحادية عشرة", "نص 11", (ADD_11_BIS,))))
    [added] = by_number(articles, ArticleNumber(11, bis=True))
    assert added.heading == "المادة الحادية عشرة مكرر"
    assert added.text == "للوزير أن يتخذ الإجراءات"
    assert added.status is ArticleStatus.AMENDED
    assert added.original_text is None
    [host] = by_number(articles, ArticleNumber(11))
    assert host.text == "نص 11"  # the host article itself is unchanged


def test_note_adding_an_article_that_already_has_a_block_does_not_duplicate_it() -> None:
    articles = build_articles(
        law(
            ArticleSource("المادة الحادية عشرة", "نص 11", (ADD_11_BIS,)),
            ArticleSource("المادة الحادية عشرة مكرر", "نص 11 مكرر"),
        )
    )
    assert len(by_number(articles, ArticleNumber(11, bis=True))) == 1


def test_block_whose_body_is_its_own_addition_note_uses_the_quoted_text() -> None:
    [article] = build_articles(law(ArticleSource("( التاسعة والسبعين مكرر )", SELF_ADDED_BODY)))
    assert article.number == ArticleNumber(79, bis=True)
    assert article.text == "يُعد طلب الاستقالة مقبولاً."
    assert article.original_text is None
    assert article.status is ArticleStatus.AMENDED


def test_articles_are_returned_in_legal_order() -> None:
    articles = build_articles(
        law(
            ArticleSource("المادة الثانية", "ب"),
            ArticleSource("المادة الأولى", "أ"),
        )
    )
    assert [a.number.value for a in articles] == [1, 2]


def test_duplicate_current_numbers_ignores_superseded_and_repealed() -> None:
    repeal = "تم إلغاء الباب الرابع عشر بموجب المرسوم الملكي ( م/1 ) وتاريخ 22 / 1 / 1435 هـ"
    articles = build_articles(
        law(
            ArticleSource("المادة الثانية", "قديم", (repeal,)),
            ArticleSource("المادة الثانية", "جديد"),
        )
    )
    assert duplicate_current_numbers(articles) == []


def test_duplicate_current_numbers_reports_real_conflicts() -> None:
    articles = build_articles(
        law(ArticleSource("المادة الثانية", "أ"), ArticleSource("المادة الثانية", "ب"))
    )
    assert duplicate_current_numbers(articles) == [ArticleNumber(2)]


def test_clean_heading_takes_the_current_number_of_a_renumbered_article() -> None:
    raw = "(المادة الحادية والثلاثون بعد المائتين حالياً) (المادة الأربعون بعد المائتين سابقاً)"
    assert clean_heading(raw) == "المادة الحادية والثلاثون بعد المائتين"
    assert article_title(raw) is None


def test_article_title_is_none_when_nothing_follows_the_colon() -> None:
    assert article_title("المادة الأولى :") is None
