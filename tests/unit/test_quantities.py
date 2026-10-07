"""Tests for extracting quantities from Arabic text and converting units."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.quantities import (
    Quantity,
    Unit,
    convert,
    extract_quantities,
    fold,
    iter_folded_matches,
)

D, W, M, Y, H, P = Unit.DAY, Unit.WEEK, Unit.MONTH, Unit.YEAR, Unit.HOUR, Unit.PERCENT


def values(text: str) -> list[tuple[float, Unit]]:
    return [(q.value, q.unit) for q in extract_quantities(text)]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # digits
        ("90 يوماً", [(90, D)]),
        ("٩٠ يوماً", [(90, D)]),
        ("۹۰ يوم", [(90, D)]),
        ("7.5 ساعات", [(7.5, H)]),
        ("٧٫٥ ساعة", [(7.5, H)]),
        ("30يوماً", [(30, D)]),
        # units in every form
        ("3 أيام", [(3, D)]),
        ("15 يوم", [(15, D)]),
        ("4 أسابيع", [(4, W)]),
        ("12 أسبوعاً", [(12, W)]),
        ("6 أشهر", [(6, M)]),
        ("6 شهور", [(6, M)]),
        ("11 شهراً", [(11, M)]),
        ("3 سنوات", [(3, Y)]),
        ("سبعة أعوام", [(7, Y)]),
        ("15 عاماً", [(15, Y)]),
        ("8 ساعات", [(8, H)]),
        # duals carry the number
        ("يومان", [(2, D)]),
        ("يومين", [(2, D)]),
        ("أسبوعين", [(2, W)]),
        ("شهرين", [(2, M)]),
        ("سنتين", [(2, Y)]),
        ("عامين", [(2, Y)]),
        ("ساعتين", [(2, H)]),
        ("لمدة شهرين", [(2, M)]),
        # one, stated as unit + واحد
        ("يوم واحد", [(1, D)]),
        ("سنة واحدة", [(1, Y)]),
        # number words, both cases
        ("ثلاثة أيام", [(3, D)]),
        ("ثلاث سنوات", [(3, Y)]),
        ("ستون يوماً", [(60, D)]),
        ("ستين يوماً", [(60, D)]),
        ("تسعون يوماً", [(90, D)]),
        ("تسعين يوماً", [(90, D)]),
        ("عشرة أيام", [(10, D)]),
        ("ثماني ساعات", [(8, H)]),
        # compounds and teens
        ("مائة وثمانون يوماً", [(180, D)]),
        ("مائة وثمانين يوماً", [(180, D)]),
        ("مئة وعشرين يوماً", [(120, D)]),
        ("واحد وعشرون يوماً", [(21, D)]),
        ("واحد وعشرين يومًا", [(21, D)]),
        ("ثمان وأربعين ساعة", [(48, H)]),
        ("ست وثلاثين ساعة", [(36, H)]),
        ("اثنا عشر أسبوعاً", [(12, W)]),
        ("اثني عشر أسبوعاً", [(12, W)]),
        ("اثنتي عشرة ساعة", [(12, H)]),
        ("خمسة عشر يوماً", [(15, D)]),
        ("إحدى عشرة سنة", [(11, Y)]),
        ("مائة وخمسة وعشرون يوماً", [(125, D)]),
        ("مائة واثنا عشر يوماً", [(112, D)]),
        ("مائتا يوم", [(200, D)]),
        ("ثلاثمائة يوم", [(300, D)]),
        ("ثلاث مائة يوم", [(300, D)]),
        # clitics on the number
        ("بتسعين يوماً", [(90, D)]),
        ("الثلاثين يومًا الأولى", [(30, D)]),
        ("والستين يوماً التالية", [(60, D)]),
        # parentheses and repeated numbers
        ("(مائة وثمانين) يوماً", [(180, D)]),
        ("(ستين) يوماً", [(60, D)]),
        ("ستين (60) يوماً", [(60, D)]),
        ("90 (تسعون) يوماً", [(90, D)]),
        ("(90) يوماً", [(90, D)]),
        ("ستين (90) يوماً", [(60, D), (90, D)]),
        # fractions
        ("نصف ساعة", [(0.5, H)]),
        ("نصف شهر", [(0.5, M)]),
        ("ربع ساعة", [(0.25, H)]),
        ("ساعة ونصف", [(1.5, H)]),
        ("ثلاثة أشهر ونصف", [(3.5, M)]),
        ("سنة وربع", [(1.25, Y)]),
        # percentages
        ("50%", [(50, P)]),
        ("%50", [(50, P)]),
        ("٥٠٪", [(50, P)]),
        ("10 بالمائة", [(10, P)]),
        ("خمسين في المائة", [(50, P)]),
        ("25 في المئة", [(25, P)]),
        # several in one sentence
        ("بأجر عن الثلاثين يومًا الأولى، وبثلاثة أرباع الأجر عن الستين يومًا", [(30, D), (60, D)]),
        # things that are not quantities
        ("شهر رمضان", []),
        ("في اليوم الواحد", []),
        ("أحد أيام الأسبوع", []),
        ("المادة 75 وعام 2024", []),
        ("عام 1446هـ", []),
        ("الساعة 8 صباحاً", []),
        ("المادة الخامسة والسبعين", []),
        ("ثلاثة أرباع الأجر", []),
        ("براتب 5000 ريال", []),
        ("يومياً وشهرياً", []),
        ("", []),
    ],
)
def test_extracts(text: str, expected: list[tuple[float, Unit]]) -> None:
    assert values(text) == expected


def test_span_covers_the_words_as_typed() -> None:
    text = "يخضع الموظف لفترة تجربة مدتها (تسعون) يوماً من تاريخ المباشرة"
    [quantity] = extract_quantities(text)
    assert text[quantity.start : quantity.end] == "(تسعون) يوماً"


def test_span_survives_diacritics_and_tatweel() -> None:
    text = "مُدَّتُها ثـلاثـون يَوْماً"
    [quantity] = extract_quantities(text)
    assert quantity.value == 30
    assert text[quantity.start : quantity.end] == "ثـلاثـون يَوْماً"


class TestQuantity:
    @pytest.mark.parametrize(
        ("value", "start", "end"),
        [(-1.0, 0, 0), (float("nan"), 0, 0), (float("inf"), 0, 0), (1.0, 5, 2), (1.0, -1, 2)],
    )
    def test_rejects_impossible_values(self, value: float, start: int, end: int) -> None:
        with pytest.raises(InvalidDomainObjectError):
            Quantity(value, D, start, end)


class TestConvert:
    @pytest.mark.parametrize(
        ("value", "source", "target", "expected"),
        [
            (2, W, D, (14, 14)),
            (14, D, W, (2, 2)),
            (2, Y, M, (24, 24)),
            (6, M, Y, (0.5, 0.5)),
            (6, M, D, (168, 186)),
            (1, Y, D, (354, 366)),
            (5, H, H, (5, 5)),
            (50, P, P, (50, 50)),
        ],
    )
    def test_ranges(
        self, value: float, source: Unit, target: Unit, expected: tuple[float, float]
    ) -> None:
        assert convert(value, source, target) == pytest.approx(expected)

    @pytest.mark.parametrize(("source", "target"), [(H, D), (D, H), (P, D), (M, P)])
    def test_incomparable_units(self, source: Unit, target: Unit) -> None:
        assert convert(1, source, target) is None


class TestFoldedMatches:
    def test_clitics_and_article_on_later_words(self) -> None:
        folded = fold("وللإجازة السنوية مدة").text
        assert list(iter_folded_matches(folded, ["إجازة سنوية"]))

    def test_word_boundary(self) -> None:
        assert not list(iter_folded_matches(fold("حجز التذاكر").text, ["حج"]))
        assert list(iter_folded_matches(fold("إجازة الحج").text, ["حج"]))


# ---------------------------------------------------------------- property tests

_ONES = ["", "واحد", "اثنان", "ثلاثة", "أربعة", "خمسة", "ستة", "سبعة", "ثمانية", "تسعة"]
_TENS = ["", "عشرة", "عشرون", "ثلاثون", "أربعون", "خمسون", "ستون", "سبعون", "ثمانون", "تسعون"]
_TEENS = ["", "أحد عشر", "اثنا عشر", "ثلاثة عشر", "أربعة عشر", "خمسة عشر", "ستة عشر"]
_TEENS += ["سبعة عشر", "ثمانية عشر", "تسعة عشر"]
_HUNDREDS = ["", "مائة", "مائتان", "ثلاثمائة", "أربعمائة", "خمسمائة", "ستمائة", "سبعمائة"]
_HUNDREDS += ["ثمانمائة", "تسعمائة"]


def to_words(number: int) -> str:
    """Reference Arabic cardinal for 1..999: hundreds, then units/teen, then tens."""
    hundreds, rest = divmod(number, 100)
    tens, ones = divmod(rest, 10)
    parts = [_HUNDREDS[hundreds]] if hundreds else []
    if rest and rest < 10:
        parts.append(_ONES[ones])
    elif rest == 10:
        parts.append(_TENS[1])
    elif 10 < rest < 20:
        parts.append(_TEENS[ones])
    elif rest:
        parts += [_ONES[ones]] if ones else []
        parts.append(_TENS[tens])
    return " و".join(parts)


@given(st.integers(min_value=1, max_value=999))
def test_number_words_round_trip(number: int) -> None:
    assert values(f"مدتها {to_words(number)} يوماً") == [(number, D)]


@given(st.integers(min_value=0, max_value=100_000))
def test_arabic_indic_digits_equal_latin_digits(number: int) -> None:
    indic = str(number).translate({ord(str(d)): chr(0x0660 + d) for d in range(10)})
    assert values(f"{indic} ساعة") == values(f"{number} ساعة") == [(number, H)]


@given(st.text(max_size=200))
def test_never_raises_and_spans_stay_inside(text: str) -> None:
    for quantity in extract_quantities(text):
        assert 0 <= quantity.start <= quantity.end <= len(text)


@given(
    st.text(alphabet="ابتثجحخدذرزسشصضطظعغفقكلمنهوي ،.", max_size=40),
    st.integers(min_value=1, max_value=500),
    st.sampled_from(["يوماً", "أسبوعاً", "شهراً", "ساعة", "سنة"]),
)
def test_embedded_quantity_is_found_with_its_span(prefix: str, number: int, unit: str) -> None:
    text = f"{prefix} {number} {unit} انتهى"
    spans = [text[q.start : q.end] for q in extract_quantities(text) if q.value == number]
    assert f"{number} {unit}" in spans
