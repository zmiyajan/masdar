"""Tests for clause splitting and rule matching in the contract checker."""

import dataclasses

import pytest
from hypothesis import given
from hypothesis import strategies as st

from masdar.domain.amendments import ArticleStatus
from masdar.domain.compliance import (
    Clause,
    ClauseReport,
    Comparator,
    ContractReport,
    FindingKind,
    ReviewReason,
    Rule,
    check_clause,
    clause_query,
    format_quantity,
    split_clauses,
)
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.labor_rules import LABOR_RULES, PROBATION_MAX
from masdar.domain.quantities import Quantity, Unit
from masdar.domain.search import MAX_QUERY_CHARS

V, C, R = FindingKind.VIOLATION, FindingKind.COMPLIANT, FindingKind.REVIEW_NEEDED

# ------------------------------------------------------------------- splitting


class TestSplitClauses:
    def test_lines_numbers_bullets_and_ordinals(self) -> None:
        text = (
            "عقد عمل\n"
            "1- يخضع الموظف لفترة تجربة 90 يوماً.\n"
            "٢) الإجازة السنوية 21 يوماً.\n"
            "• ساعات العمل 8 ساعات يومياً\n"
            "أولاً: الأجر 5000 ريال.\n"
            "  \n"
            "(3) سرية المعلومات."
        )
        clauses = split_clauses(text)
        assert [c.text for c in clauses] == [
            "عقد عمل",
            "1- يخضع الموظف لفترة تجربة 90 يوماً.",
            "٢) الإجازة السنوية 21 يوماً.",
            "• ساعات العمل 8 ساعات يومياً",
            "أولاً: الأجر 5000 ريال.",
            "(3) سرية المعلومات.",
        ]
        assert [c.index for c in clauses] == [1, 2, 3, 4, 5, 6]

    def test_inline_items_split_only_after_a_sentence_end(self) -> None:
        text = "البند الأول: مدة العقد سنة. البند الثاني: التجربة 90 يوماً؛ 3- الإجازة 21 يوماً"
        assert [c.text for c in split_clauses(text)] == [
            "البند الأول: مدة العقد سنة.",
            "البند الثاني: التجربة 90 يوماً؛",
            "3- الإجازة 21 يوماً",
        ]

    def test_decimals_and_mid_sentence_numbers_do_not_split(self) -> None:
        text = "يعمل الموظف 7.5 ساعات يومياً و 2- لا شيء"
        assert [c.text for c in split_clauses(text)] == [text]

    def test_blank_and_marker_only_lines_are_dropped(self) -> None:
        assert split_clauses("\n  \n1-\n•\n") == []

    @given(st.lists(st.text(alphabet="ابتث 0123456789-.:؛\n•()", max_size=30), max_size=8))
    def test_spans_reproduce_the_text(self, parts: list[str]) -> None:
        text = "\n".join(parts)
        for clause in split_clauses(text):
            assert text[clause.start : clause.end] == clause.text
            assert clause.text == clause.text.strip()


def test_clause_query_fits_the_search_limit() -> None:
    long_clause = "كلمة " * 200
    query = clause_query(long_clause)
    assert len(query) <= MAX_QUERY_CHARS
    assert query.endswith("كلمة")
    assert clause_query("  نص   قصير ") == "نص قصير"
    assert len(clause_query("ب" * 600)) == MAX_QUERY_CHARS


# ---------------------------------------------------------------- rule matching


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # probation (Art. 53): total of 180 days
        ("يخضع الموظف لفترة تجربة مدتها تسعون يوماً.", {"probation-max": (C, None)}),
        ("مدة التجربة 181 يوماً.", {"probation-max": (V, None)}),
        ("مدة التجربة مائة وثمانون يوماً.", {"probation-max": (C, None)}),
        ("فترة التجربة ستة أشهر.", {"probation-max": (R, ReviewReason.INEXACT_CONVERSION)}),
        ("فترة التجربة 5 أشهر.", {"probation-max": (C, None)}),
        ("فترة التجربة 90 يوماً قابلة للتمديد.", {"probation-max": (R, ReviewReason.OPEN_TOTAL)}),
        ("فترة التجربة 90 يوماً قابلة للتمديد لمدة مماثلة.", {"probation-max": (C, None)}),
        ("فترة التجربة 100 يوم قابلة للتمديد لمدة مماثلة.", {"probation-max": (V, None)}),
        ("فترة التجربة 90 يوماً قابلة للتمديد 90 يوماً.", {"probation-max": (C, None)}),
        ("فترة التجربة 120 يوماً قابلة للتمديد 90 يوماً.", {"probation-max": (V, None)}),
        (
            "فترة التجربة 4 أشهر قابلة للتمديد شهرين.",
            {"probation-max": (R, ReviewReason.OPEN_TOTAL)},
        ),
        ("التجربة 90 يوماً ولا يتجاوز مجموعها 180 يوماً.", {"probation-max": (C, None)}),
        ("لا تخضع الوظيفة لفترة تجربة.", {}),
        # notice (Art. 75): employer side, indefinite contracts only
        (
            "العقد غير محدد المدة ويحق لأي من الطرفين إنهاؤه بإشعار 30 يوماً.",
            {"notice-employer-min": (V, None)},
        ),
        (
            "يحق لأي من الطرفين إنهاء العقد بإشعار 30 يوماً.",
            {"notice-employer-min": (R, ReviewReason.CONDITION_NOT_STATED)},
        ),
        (
            "العقد غير محدد المدة ويحق للشركة إنهاؤه بإشعار 30 يوماً للعامل باليومية.",
            {"notice-employer-min": (R, ReviewReason.POSSIBLE_EXCEPTION)},
        ),
        ("يلتزم الموظف بإشعار الشركة قبل 30 يوماً من استقالته.", {}),
        # hours (Art. 98, with the Art. 99 nine-hour exception)
        ("ساعات العمل 8 ساعات يومياً.", {"daily-hours-max": (C, None)}),
        (
            "ساعات العمل 9 ساعات يومياً.",
            {"daily-hours-max": (R, ReviewReason.POSSIBLE_EXCEPTION)},
        ),
        ("يعمل الموظف 11 ساعة في اليوم.", {"daily-hours-max": (V, None)}),
        (
            "يعمل الحارس 12 ساعة يومياً بنظام المناوبة.",
            {"daily-hours-max": (R, ReviewReason.POSSIBLE_EXCEPTION)},
        ),
        ("يعمل الموظف 45 ساعة أسبوعياً.", {"weekly-hours-max": (C, None)}),
        ("يعمل الموظف 8 ساعات.", {}),
        (
            "ساعات الدوام في رمضان 7 ساعات يومياً.",
            {"ramadan-daily-hours-max": (V, None)},
        ),
        (
            "ساعات العمل في رمضان 40 ساعة أسبوعياً لغير المسلمين.",
            {"ramadan-weekly-hours-max": (R, ReviewReason.POSSIBLE_EXCEPTION)},
        ),
        # overtime (Art. 107) is under review: never a hard verdict
        (
            "أجر العمل الإضافي هو أجر الساعة مضافاً إليه 10%.",
            {"overtime-rate-min": (R, ReviewReason.ARTICLE_UNDER_REVIEW)},
        ),
        (
            "أجر العمل الإضافي هو أجر الساعة مضافاً إليه 50%.",
            {"overtime-rate-min": (R, ReviewReason.ARTICLE_UNDER_REVIEW)},
        ),
        # leaves
        ("الإجازة السنوية 21 يوماً.", {"annual-leave-min": (C, None)}),
        ("الإجازة السنوية أسبوعان.", {"annual-leave-min": (V, None)}),
        ("لا تستحق الإجازة السنوية قبل مرور 90 يوماً.", {}),
        (
            "الإجازة السنوية 15 يوماً، وتزاد إلى 21 يوماً بعد خمس سنوات.",
            {"annual-leave-min": (V, None), "annual-leave-5y-min": (V, None)},
        ),
        ("إجازة الوضع عشرة أسابيع.", {"maternity-leave-min": (V, None)}),
        ("إجازة الوضع 84 يوماً.", {"maternity-leave-min": (C, None)}),
        ("إجازة الوضع شهران ونصف.", {"maternity-leave-min": (V, None)}),
        ("إجازة الأمومة ثلاثة أشهر.", {"maternity-leave-min": (C, None)}),
        (
            "إجازة الوضع 12 أسبوعاً ويجوز تمديدها شهراً واحداً دون أجر.",
            {"maternity-leave-min": (C, None)},
        ),
        ("إجازة مرضية بأجر كامل 30 يوماً.", {"sick-leave-full-pay-min": (C, None)}),
        ("إجازة مرضية 10 أيام.", {}),
        ("إجازة الحج 10 أيام.", {"hajj-leave-min": (C, None)}),
        ("إجازة الزواج 5 أيام.", {"marriage-leave-min": (C, None)}),
        ("إجازة عند ولادة مولود له يومان.", {"paternity-leave-min": (V, None)}),
        # others
        ("شرط عدم المنافسة لمدة 30 شهراً.", {"non-compete-max": (V, None)}),
        ("شرط عدم المنافسة لمدة سنة ونصف.", {"non-compete-max": (C, None)}),
        ("يخصم 10% من الراتب لسداد القرض.", {"loan-deduction-max": (C, None)}),
        (
            "يخصم 30% من الراتب لسداد القرض بموافقة كتابية.",
            {"loan-deduction-max": (R, ReviewReason.POSSIBLE_EXCEPTION)},
        ),
        ("يتقاضى الموظف بدل سكن 25% من الراتب الأساسي.", {}),
        ("", {}),
    ],
)
def test_rules(text: str, expected: dict[str, tuple[FindingKind, ReviewReason | None]]) -> None:
    findings = check_clause(text, LABOR_RULES)
    assert {f.rule_id: (f.kind, f.reason) for f in findings} == expected


def test_message_cites_the_article_and_the_numbers() -> None:
    [finding] = check_clause("فترة التجربة في البند 200 يوم", [PROBATION_MAX])
    assert finding.kind is V
    assert finding.message == (
        "فترة التجربة في البند 200 يوم، والحد الأعلى في نظام العمل "
        "(المادة الثالثة والخمسون) 180 يوماً: البند يخالف النظام."
    )
    assert [q.value for q in finding.stated] == [200]


def test_review_message_explains_why() -> None:
    [finding] = check_clause("فترة التجربة ستة أشهر", [PROBATION_MAX])
    assert "يحتاج إلى مراجعة" in finding.message
    assert "28 إلى 31" in finding.message


def test_article_under_review_downgrades_even_a_clear_violation() -> None:
    doubtful = dataclasses.replace(PROBATION_MAX, article_status=ArticleStatus.REVIEW_NEEDED)
    [finding] = check_clause("فترة التجربة 300 يوم", [doubtful])
    assert (finding.kind, finding.reason) == (R, ReviewReason.ARTICLE_UNDER_REVIEW)


class TestRuleValidation:
    def make(self, **changes: object) -> Rule:
        return dataclasses.replace(PROBATION_MAX, **changes)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        "changes",
        [
            {"rule_id": " "},
            {"article_id": "no-colon"},
            {"cues": ()},
            {"cues": ((),)},
            {"units": frozenset({Unit.WEEK})},
            {"units": frozenset({Unit.DAY, Unit.HOUR})},
        ],
    )
    def test_rejects_rules_that_cannot_work(self, changes: dict[str, object]) -> None:
        with pytest.raises(InvalidDomainObjectError):
            self.make(**changes)

    def test_law_and_citation(self) -> None:
        assert PROBATION_MAX.law_id == "labor-law"
        assert PROBATION_MAX.citation == "نظام العمل (المادة الثالثة والخمسون)"
        assert PROBATION_MAX.comparator is Comparator.MAXIMUM

    def test_rule_ids_are_unique(self) -> None:
        ids = [rule.rule_id for rule in LABOR_RULES]
        assert len(ids) == len(set(ids))


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (1, Unit.DAY, "1 يوم"),
        (2, Unit.WEEK, "أسبوعان"),
        (3, Unit.MONTH, "3 أشهر"),
        (10, Unit.DAY, "10 أيام"),
        (12, Unit.WEEK, "12 أسبوعاً"),
        (100, Unit.DAY, "100 يوم"),
        (103, Unit.DAY, "103 أيام"),
        (0.5, Unit.MONTH, "0.5 شهر"),
        (8, Unit.HOUR, "8 ساعات"),
        (50, Unit.PERCENT, "50%"),
    ],
)
def test_format_quantity(value: float, unit: Unit, expected: str) -> None:
    assert format_quantity(value, unit) == expected


def test_contract_report_counts() -> None:
    clause = Clause(1, "فترة التجربة 200 يوم", 0, 20)
    findings = check_clause(clause.text, LABOR_RULES)
    report = ContractReport((ClauseReport(clause, findings), ClauseReport(clause, ())))
    assert report.counts == {V: 1, C: 0, R: 0}
    assert (report.violations, report.compliant, report.review_needed) == (1, 0, 0)


def test_limit_quantity_is_a_plain_quantity() -> None:
    assert PROBATION_MAX.limit == Quantity(180, Unit.DAY)
