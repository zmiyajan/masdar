"""Tests for the BOE HTML parser on small, hand-written pages.

The markup mirrors the real portal; tests on the real pages live in
``tests/integration/test_boe_snapshots.py``.
"""

import pytest

from masdar.adapters.boe.parser import parse_law_html
from masdar.domain.errors import SourceFormatError

PAGE = """
<html><body>
<h1 class="system_title">نظام العمل</h1>
<h3 class="center">الباب الأول: التعريفات</h3>
<div class="article_item no_alternate ">
  <h3 class="center">الفصل الأول : التعريفات</h3>
  <h3 class="center">المادة الأولى :</h3>
  <div class="article_btns"></div>
  <p><div class="HTMLContainer">يسمى هذا النظام <strong>نظام العمل</strong>.</div></p>
</div>
<div class="article_item no_alternate changed-article">
  <h3 class="center">المادة الثانية</h3>
  <div class="popup-list">
    <div class="article_item_popup">
      <h3>المادة الثانية</h3>
      <div class="HTMLContainer">تم تعديل هذه المادة لتكون بالنص الآتي: "نص جديد"</div>
    </div>
  </div>
  <p><div class="HTMLContainer">1- الفقرة الأولى<br/>2- الفقرة&nbsp;الثانية<!-- note --></div></p>
</div>
<h3 class="center">الباب الثاني: التوظيف</h3>
<div class="article_item no_alternate ">
  <h3 class="center">المادة الثالثة</h3>
  <p><div class="HTMLContainer">العمل حق للمواطن.</div></p>
</div>
</body></html>
"""


def test_extracts_title_articles_structure_and_notes() -> None:
    law = parse_law_html(PAGE, law_id="labor-law", source_url="https://example.test")
    assert law.title == "نظام العمل"
    assert [s.heading for s in law.sources] == [
        "المادة الأولى :",
        "المادة الثانية",
        "المادة الثالثة",
    ]

    first, second, third = law.sources
    assert (first.part, first.chapter) == ("الباب الأول: التعريفات", "الفصل الأول : التعريفات")
    assert first.body == "يسمى هذا النظام نظام العمل."
    assert second.chapter == "الفصل الأول : التعريفات"  # chapter carries over
    assert (third.part, third.chapter) == ("الباب الثاني: التوظيف", None)  # new part resets it


def test_body_excludes_amendment_popups_and_keeps_line_breaks() -> None:
    second = parse_law_html(PAGE, law_id="x", source_url="u").sources[1]
    assert second.body == "1- الفقرة الأولى\n2- الفقرة الثانية"
    assert second.notes == ('تم تعديل هذه المادة لتكون بالنص الآتي: "نص جديد"',)


def test_parsing_is_repeatable_on_the_same_input() -> None:
    assert parse_law_html(PAGE, law_id="x", source_url="u") == parse_law_html(
        PAGE, law_id="x", source_url="u"
    )


@pytest.mark.parametrize(
    ("html", "message"),
    [
        pytest.param("<html></html>", "no law title", id="no-title"),
        pytest.param('<h1 class="system_title">ن</h1>', "no article blocks", id="no-articles"),
        pytest.param(
            '<h1 class="system_title">ن</h1><div class="article_item"><p>نص</p></div>',
            "without a heading",
            id="block-without-heading",
        ),
        pytest.param(
            '<h1 class="system_title">ن</h1><div class="article_item"><h3>المادة الأولى</h3></div>',
            "no article body",
            id="block-without-body",
        ),
    ],
)
def test_rejects_unexpected_markup(html: str, message: str) -> None:
    with pytest.raises(SourceFormatError, match=message):
        parse_law_html(html, law_id="x", source_url="u")
