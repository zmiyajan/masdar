"""Tests for amendment parsing and resolution.

The notes below are shortened from real notes on laws.boe.gov.sa, keeping the
wording that drives classification.
"""

import pytest

from masdar.domain.amendments import (
    Amendment,
    AmendmentKind,
    ArticleStatus,
    HijriDate,
    extract_quoted_text,
    parse_amendment,
    resolve,
    split_consolidated_text,
)
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.ordinals import ArticleNumber

REPLACE_1446 = (
    "- صدر المرسوم الملكي رقم (م/44) وتاريخ 1446/2/8هـ، وذلك بالموافقة على تعديلات بعض مواد "
    "نظام العمل (ويعمل بها من تاريخ 1446/8/20هـ) وعدلت هذه المادة لتكون بالنص الآتي: "
    '" 1- يستثنى من تطبيق أحكام هذا النظام كل من: أ- أفراد أسرة صاحب العمل."'
)
REPLACE_1436 = (
    "تم تعديل هذه المادة بموجب المرسوم الملكي رقم ( م/ 46) وتاريخ 5 / 6 / 1436 هـ ؛ "
    'لتكون بالنص الآتي : " تسري أحكام هذا النظام على الآتي "'
)
ADD_ELSEWHERE = (
    "تم إضافة مادة تحمل الرقم (الحادية عشرة مكرر) بموجب المرسوم الملكي رقم ( م/ 46) "
    'وتاريخ 5 / 6 / 1436 هـ ؛ بالنص الآتي : "للوزير أن يتخذ الإجراءات".'
)
ADD_SELF = (
    "- اُضيفت هذه المادة بموجب المرسوم الملكي رقم (م/44) وتاريخ 1446/2/8هـ، وتكون بالنص "
    'الآتي: "1- يُعد طلب الاستقالة المقدم مقبولاً إذا مضى على تقديمه (ثلاثون) يوماً."'
)
REPEAL_PART = "تم إلغاء الباب الرابع عشر بموجب المرسوم الملكي ( م/1 ) وتاريخ 22 / 1 / 1435 هـ"
REPEAL_ARTICLE = "- أُلغيت هذه المادة بموجب المرسوم الملكي رقم (م/148) وتاريخ 1444/9/5هـ"
PARTIAL_WORD = (
    '- إحلال كلمة "صريحة" محل كلمة "كتابية" الواردة في الفقرة (1) من هذه المادة، وذلك بموجب '
    "المرسوم الملكي رقم (م/148) وتاريخ 1444/9/5هـ"
)
RENUMBER = (
    "تم تعديل هذه المادة ونقلها لتكون (الحادية والثلاثين بعد المائتين) بموجب المرسوم "
    "الملكي رقم ( م/ 46) وتاريخ 5 / 6 / 1436 هـ"
)
CONSOLIDATE = (
    "تم تعديل أحكام المواد (الثانية عشرة) و(الثالثة عشرة) و(الرابعة عشرة)؛ وإعادة صياغتها "
    "بعد تعديل أحكامها لتكون في مادتين بموجب المرسوم الملكي رقم ( م/ 46) وتاريخ 5 / 6 / 1436 هـ ؛ "
    'على النحو الآتي : "المادة الثانية عشرة : تضع الوزارة نموذجاً موحداً، وفق أحكام المادة '
    'الرابعة عشرة السابقة. المادة الثالثة عشرة : تطبق أحكام اللائحة على العمال."'
)


@pytest.mark.parametrize(
    ("note", "kind"),
    [
        pytest.param(REPLACE_1446, AmendmentKind.REPLACE, id="replace-1446"),
        pytest.param(REPLACE_1436, AmendmentKind.REPLACE, id="replace-1436"),
        pytest.param(ADD_ELSEWHERE, AmendmentKind.ADD, id="add-other-article"),
        pytest.param(ADD_SELF, AmendmentKind.ADD, id="add-this-article"),
        pytest.param(REPEAL_PART, AmendmentKind.REPEAL, id="repeal-part"),
        pytest.param(REPEAL_ARTICLE, AmendmentKind.REPEAL, id="repeal-article"),
        pytest.param(PARTIAL_WORD, AmendmentKind.PARTIAL, id="partial-word"),
        pytest.param(RENUMBER, AmendmentKind.RENUMBER, id="renumber"),
        pytest.param(CONSOLIDATE, AmendmentKind.CONSOLIDATE, id="consolidate"),
        pytest.param("ملاحظة غير معروفة", AmendmentKind.PARTIAL, id="unknown-is-safe-partial"),
    ],
)
def test_classifies_notes(note: str, kind: AmendmentKind) -> None:
    assert parse_amendment(note).kind is kind


def test_extracts_decree_and_both_date_formats() -> None:
    year_first = parse_amendment(REPLACE_1446)
    assert year_first.decree == "م/44"
    assert year_first.issued == HijriDate(1446, 2, 8)
    assert year_first.effective == HijriDate(1446, 8, 20)

    day_first = parse_amendment(REPLACE_1436)
    assert day_first.decree == "م/46"
    assert day_first.issued == HijriDate(1436, 6, 5)
    assert day_first.effective is None


def test_add_note_records_target_article_and_label() -> None:
    amendment = parse_amendment(ADD_ELSEWHERE)
    assert amendment.target == ArticleNumber(11, bis=True)
    assert amendment.target_label == "الحادية عشرة مكرر"
    assert amendment.new_text == "للوزير أن يتخذ الإجراءات"


def test_consolidation_records_redrafted_articles() -> None:
    assert parse_amendment(CONSOLIDATE).consolidated == (
        ArticleNumber(12),
        ArticleNumber(13),
        ArticleNumber(14),
    )


class TestExtractQuotedText:
    @pytest.mark.parametrize(
        ("note", "expected"),
        [
            pytest.param('لتكون بالنص الآتي: "نص جديد"', "نص جديد", id="straight-quotes"),
            pytest.param("لتكون بالنص الآتي: “نص جديد”", "نص جديد", id="curly-quotes"),
            pytest.param("لتكون بالنص الآتي: «نص جديد»", "نص جديد", id="guillemets"),
            pytest.param(
                'بالنص الآتي: "يضاف "أو من ينيبه" بعد الوزير"',
                'يضاف "أو من ينيبه" بعد الوزير',
                id="inner-quotes-survive",
            ),
        ],
    )
    def test_quote_styles(self, note: str, expected: str) -> None:
        assert extract_quoted_text(note) == expected

    @pytest.mark.parametrize(
        "note",
        [
            pytest.param("أُلغيت هذه المادة", id="no-keyword"),
            pytest.param('لتكون بالنص الآتي: "', id="unclosed"),
            pytest.param('لتكون بالنص الآتي: "  "', id="blank"),
        ],
    )
    def test_returns_none_without_a_usable_quote(self, note: str) -> None:
        assert extract_quoted_text(note) is None


class TestResolve:
    number = ArticleNumber(7)

    def test_no_amendments_means_in_force(self) -> None:
        assert resolve(self.number, "نص", ()).status is ArticleStatus.IN_FORCE

    def test_latest_decree_wins_regardless_of_published_order(self) -> None:
        resolution = resolve(
            self.number,
            "الأصل",
            (parse_amendment(REPLACE_1446), parse_amendment(REPLACE_1436)),
        )
        assert resolution.status is ArticleStatus.AMENDED
        assert resolution.text.startswith("1- يستثنى")

    def test_partial_after_replace_needs_review_and_keeps_last_certain_text(self) -> None:
        resolution = resolve(
            self.number, "الأصل", (parse_amendment(REPLACE_1436), parse_amendment(PARTIAL_WORD))
        )
        assert resolution.status is ArticleStatus.REVIEW_NEEDED
        assert resolution.text == "تسري أحكام هذا النظام على الآتي"

    def test_repeal_is_not_undone_by_a_later_partial_edit(self) -> None:
        resolution = resolve(
            self.number, "الأصل", (parse_amendment(REPEAL_PART), parse_amendment(PARTIAL_WORD))
        )
        assert resolution.status is ArticleStatus.REPEALED

    def test_add_note_for_another_article_leaves_this_one_untouched(self) -> None:
        resolution = resolve(ArticleNumber(11), "الأصل", (parse_amendment(ADD_ELSEWHERE),))
        assert resolution == resolve(ArticleNumber(11), "الأصل", ())

    def test_renumbering_keeps_the_text(self) -> None:
        resolution = resolve(ArticleNumber(231), "الأصل", (parse_amendment(RENUMBER),))
        assert (resolution.status, resolution.text) == (ArticleStatus.IN_FORCE, "الأصل")

    @pytest.mark.parametrize(
        ("number", "status", "text_start"),
        [
            (ArticleNumber(12), ArticleStatus.AMENDED, "تضع الوزارة"),
            (ArticleNumber(13), ArticleStatus.AMENDED, "تطبق أحكام"),
            (ArticleNumber(14), ArticleStatus.SUPERSEDED, "الأصل"),
        ],
    )
    def test_consolidation(
        self, number: ArticleNumber, status: ArticleStatus, text_start: str
    ) -> None:
        resolution = resolve(number, "الأصل", (parse_amendment(CONSOLIDATE),))
        assert resolution.status is status
        assert resolution.text.startswith(text_start)

    def test_superseded_is_not_revived_by_a_later_partial_edit(self) -> None:
        later_partial = parse_amendment(PARTIAL_WORD)
        resolution = resolve(
            ArticleNumber(14), "الأصل", (parse_amendment(CONSOLIDATE), later_partial)
        )
        assert resolution.status is ArticleStatus.SUPERSEDED

    def test_replacement_text_drops_its_own_heading(self) -> None:
        note = (
            "تم تعديل هذه المادة ونقلها بموجب المرسوم الملكي رقم ( م/ 46) وتاريخ 5 / 6 / 1436 هـ ؛ "
            'لتكون بالنص الآتي : "المادة الحادية والثلاثون بعد المائتين : يلزم مرتكب المخالفة"'
        )
        assert resolve(ArticleNumber(231), "الأصل", (parse_amendment(note),)).text == (
            "يلزم مرتكب المخالفة"
        )

    def test_unsplittable_consolidation_is_flagged_not_guessed(self) -> None:
        broken = Amendment(
            kind=AmendmentKind.CONSOLIDATE,
            note="...",
            new_text="نص بلا عناوين مواد",
            consolidated=(ArticleNumber(12), ArticleNumber(14)),
        )
        assert resolve(ArticleNumber(14), "الأصل", (broken,)).status is ArticleStatus.REVIEW_NEEDED


def test_split_ignores_article_references_inside_the_body() -> None:
    quote = parse_amendment(CONSOLIDATE).new_text
    assert quote is not None
    slices = split_consolidated_text(
        quote, (ArticleNumber(12), ArticleNumber(13), ArticleNumber(14))
    )
    assert set(slices) == {ArticleNumber(12), ArticleNumber(13)}
    assert "الرابعة عشرة السابقة" in slices[ArticleNumber(12)]


class TestHijriDate:
    def test_orders_chronologically(self) -> None:
        assert HijriDate(1436, 6, 5) < HijriDate(1446, 2, 8)

    def test_formats_zero_padded(self) -> None:
        assert str(HijriDate(1446, 2, 8)) == "1446/02/08"

    @pytest.mark.parametrize(("year", "month", "day"), [(1446, 13, 1), (1446, 1, 31), (999, 1, 1)])
    def test_rejects_impossible_dates(self, year: int, month: int, day: int) -> None:
        with pytest.raises(InvalidDomainObjectError):
            HijriDate(year, month, day)

    def test_impossible_date_in_a_note_is_ignored(self) -> None:
        assert parse_amendment("بموجب المرسوم رقم (م/1) وتاريخ 40/13/1446هـ").issued is None


EDIT_LIST = (
    "- صدر المرسوم الملكي رقم (م/44) وتاريخ 1446/2/8هـ، وعُدلت هذه المادة على النحو الآتي:\n"
    '- عُدل صدر هذه المادة ليكون بالنص الآتي "توفر الوزارة قنوات للتوظيف:".\n'
    '- عُدلت الفقرة (3/3) لتكون بالنص الآتي: "مواءمة طلبات طالبي العمل".'
)
DUAL_CONSOLIDATE = (
    "تم تعديل أحكام المادتين (الحادية والخمسين بعد المائة) و(الثانية والخمسين بعد المائة)؛ "
    "وإعادة صياغتهما لتكون في مادة واحدة بموجب المرسوم الملكي رقم ( م/ 46) "
    "وتاريخ 5 / 6 / 1436 هـ ؛ "
    'على النحو الآتي : "المادة الحادية والخمسون بعد المائة : للمرأة العاملة الحق في إجازة وضع."'
)
ADD_BY_ORDER = (
    "إضافة مادة يكون ترتيبها (الحادية والثلاثين بعد المائة مكرر) بموجب المرسوم الملكي "
    '( م/ 46) وتاريخ 5 / 6 / 1436 هـ بالنص الآتي: "يحدد الوزير المهن الخطرة."'
)
DECREE_AFTER_QUOTE = (
    '- إضافة مادة تحمل الرقم ( الرابعة والثلاثون بعد المائتين ) ليكون النص كالآتي: "أ- لا تقبل '
    'أمام المحاكم العمالية أي دعوى."\n'
    "وأضيفت هذه المادة بموجب المرسوم الملكي رقم (م/14) وتاريخ 1440/2/22هـ"
)
REPLACE_QUOTING_A_REPEAL = (
    "تم تعديل هذه المادة بموجب المرسوم الملكي رقم ( م/ 46) وتاريخ 5 / 6 / 1436 هـ ؛ لتكون بالنص "
    'الآتي: "يترتب على إلغاء الفصل المشار إليه سقوط الحق."'
)


class TestReviewRegressions:
    """One test per finding of the phase 2 review."""

    def test_note_listing_several_edits_is_partial_not_a_replacement(self) -> None:
        assert parse_amendment(EDIT_LIST).kind is AmendmentKind.PARTIAL

    def test_dual_form_consolidation(self) -> None:
        amendment = parse_amendment(DUAL_CONSOLIDATE)
        assert amendment.kind is AmendmentKind.CONSOLIDATE
        assert amendment.consolidated == (ArticleNumber(151), ArticleNumber(152))
        assert resolve(ArticleNumber(152), "قديم", (amendment,)).status is ArticleStatus.SUPERSEDED

    def test_added_article_identified_by_tartib(self) -> None:
        amendment = parse_amendment(ADD_BY_ORDER)
        assert amendment.kind is AmendmentKind.ADD
        assert amendment.target == ArticleNumber(131, bis=True)

    def test_repeal_wording_with_ilgha(self) -> None:
        note = "تم إلغاء هذه المادة بموجب المرسوم الملكي رقم (م/1) وتاريخ 1440/1/1هـ"
        assert parse_amendment(note).kind is AmendmentKind.REPEAL

    def test_words_inside_the_quoted_law_text_do_not_change_the_kind(self) -> None:
        assert parse_amendment(REPLACE_QUOTING_A_REPEAL).kind is AmendmentKind.REPLACE

    def test_decree_and_date_after_the_quote_are_read(self) -> None:
        amendment = parse_amendment(DECREE_AFTER_QUOTE)
        assert (amendment.decree, amendment.issued) == ("م/14", HijriDate(1440, 2, 22))
        assert amendment.new_text == "أ- لا تقبل أمام المحاكم العمالية أي دعوى."

    def test_bitarikh_date_wording(self) -> None:
        note = "بموجب المرسوم الملكي (م/46) الصادر بتاريخ 5 / 6 / 1436 هـ"
        assert parse_amendment(note).issued == HijriDate(1436, 6, 5)

    def test_competing_full_texts_with_an_undated_one_need_review(self) -> None:
        dated = parse_amendment(REPLACE_1436)
        undated = Amendment(kind=AmendmentKind.REPLACE, note="...", new_text="نص بلا تاريخ")
        resolution = resolve(ArticleNumber(7), "الأصل", (dated, undated))
        assert resolution.status is ArticleStatus.REVIEW_NEEDED
