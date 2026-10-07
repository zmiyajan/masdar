"""Find quantities such as ``تسعون يوماً`` or ``8 ساعات`` in Arabic text.

Contracts and laws state durations and rates in several ways: Latin or
Arabic-Indic digits (``90``, ``٩٠``), number words in either grammatical case
(``تسعون`` / ``تسعين``), compounds (``مائة وثمانون``, ``واحد وعشرون``), teens
(``اثنا عشر``), duals that carry the number in the unit itself (``شهرين``), and
fractions (``نصف شهر``, ``ساعة ونصف``). The law often repeats a number in words
and digits (``ستين (60) يوماً``); that is one quantity, not two.

Matching runs on a folded copy of the text (`fold`), which keeps an offset map
back to the input, so every `Quantity` carries a span into the text the user
pasted. Only a number followed by a unit counts: a bare number (``المادة 75``,
``عام 2024``) is not a quantity, because without a unit nothing can be compared
with the law. That keeps the extractor conservative by construction.
"""

import math
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from enum import StrEnum
from functools import cache

from masdar.domain.arabic import normalize_arabic
from masdar.domain.errors import InvalidDomainObjectError


class Unit(StrEnum):
    """The units a labor-law limit can be stated in."""

    HOUR = "hour"
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"
    PERCENT = "percent"


@dataclass(frozen=True, slots=True)
class Quantity:
    """A number with a unit, and where it was found.

    Attributes:
        value: The amount, e.g. ``180.0``; fractions such as ``0.5`` are allowed.
        unit: What is counted.
        start: Offset of the first character in the input text.
        end: Offset just past the last character (``text[start:end]``).
    """

    value: float
    unit: Unit
    start: int = 0
    end: int = 0

    def __post_init__(self) -> None:
        """A negative, infinite or NaN amount, or a reversed span, is a bug upstream."""
        if not math.isfinite(self.value) or self.value < 0:
            raise InvalidDomainObjectError(f"Quantity.value must be >= 0, got {self.value!r}")
        if self.start < 0 or self.end < self.start:
            raise InvalidDomainObjectError(f"Bad Quantity span {self.start}..{self.end}")


# ------------------------------------------------------------------------ folding

# Characters NFKC leaves alone but contracts use: the Arabic percent sign and
# the Arabic decimal separator.
_EXTRA_FOLDS = {chr(0x066A): "%", chr(0x066B): "."}


@dataclass(frozen=True, slots=True)
class FoldedText:
    """Normalized text plus a map from each of its characters back to the input.

    Attributes:
        text: The folded text (`normalize_arabic` applied per character).
        offsets: ``offsets[i]`` is the input index of ``text[i]``; one extra
            final entry holds the input length, so spans can end there.
    """

    text: str
    offsets: tuple[int, ...]

    def span(self, start: int, end: int) -> tuple[int, int]:
        """Map a span of the folded text back to a span of the input.

        The end extends over marks that fold to nothing (the tanween in
        ``يوماً``), so the span covers the word as the user typed it.
        """
        if end <= start:
            return self.offsets[start], self.offsets[start]
        return self.offsets[start], max(self.offsets[end], self.offsets[end - 1] + 1)


def fold(text: str) -> FoldedText:
    """Normalize ``text`` for matching while remembering where each character came from.

    `normalize_arabic` works on whole strings and collapses whitespace, which
    loses positions. Applying it per character keeps an exact offset map: marks
    such as tanween or tatweel fold to nothing, presentation forms may expand,
    and whitespace is kept as one space per character, except line breaks,
    which clause splitting needs.

    Example:
        >>> fold("أيامٌ").text
        'ايام'
    """
    chars: list[str] = []
    offsets: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            folded = "\n" if char == "\n" else " "
        else:
            folded = _EXTRA_FOLDS.get(char) or normalize_arabic(char)
        for out in folded:
            chars.append(out)
            offsets.append(index)
    offsets.append(len(text))
    return FoldedText("".join(chars), tuple(offsets))


# ------------------------------------------------------------------- vocabulary

# Every word is in folded form (ة→ه, ى→ي, أ/إ/آ→ا), because matching runs on
# folded text.
_UNIT_WORDS = {
    1: ("واحد", "واحده"),
    2: ("اثنان", "اثنين", "اثنتان", "اثنتين", "اثنا", "اثني", "اثنتا", "اثنتي"),
    3: ("ثلاث", "ثلاثه"),
    4: ("اربع", "اربعه"),
    5: ("خمس", "خمسه"),
    6: ("ست", "سته"),
    7: ("سبع", "سبعه"),
    8: ("ثمان", "ثماني", "ثمانيه"),
    9: ("تسع", "تسعه"),
    10: ("عشر", "عشره"),
}
# "احد" alone means "one of" (احد ايام الاسبوع), so it only counts inside a teen.
_TEEN_ONE = ("احد", "احدي")
_TEEN_MARKER = ("عشر", "عشره")
_TENS_WORDS = {
    20: ("عشرون", "عشرين"),
    30: ("ثلاثون", "ثلاثين"),
    40: ("اربعون", "اربعين"),
    50: ("خمسون", "خمسين"),
    60: ("ستون", "ستين"),
    70: ("سبعون", "سبعين"),
    80: ("ثمانون", "ثمانين"),
    90: ("تسعون", "تسعين"),
}
_HUNDRED_WORDS = {
    100: ("مائه", "مئه"),
    200: ("مائتان", "مائتين", "مئتان", "مئتين", "مائتا", "مائتي"),
    **{
        unit * 100: (f"{word}مائه", f"{word}مئه")
        for unit, word in ((3, "ثلاث"), (4, "اربع"), (5, "خمس"), (6, "ست"), (7, "سبع"))
    },
    800: ("ثمانمائه", "ثمانمئه", "ثمانيمائه"),
    900: ("تسعمائه", "تسعمئه"),
}

_UNITS: dict[str, int] = {w: v for v, words in _UNIT_WORDS.items() for w in words}
_TENS: dict[str, int] = {w: v for v, words in _TENS_WORDS.items() for w in words}
_HUNDREDS: dict[str, int] = {w: v for v, words in _HUNDRED_WORDS.items() for w in words}
_HUNDRED_MULTIPLIER = ("مائه", "مئه")

_UNIT_NOUNS: dict[str, Unit] = {
    **dict.fromkeys(("ساعه", "ساعات"), Unit.HOUR),
    **dict.fromkeys(("يوم", "ايام", "يوما"), Unit.DAY),
    **dict.fromkeys(("اسبوع", "اسابيع", "اسبوعا"), Unit.WEEK),
    **dict.fromkeys(("شهر", "اشهر", "شهور", "شهرا"), Unit.MONTH),
    **dict.fromkeys(("سنه", "سنوات", "سنين", "عام", "اعوام", "عاما"), Unit.YEAR),
}
_SINGULAR_NOUNS: dict[str, Unit] = {
    "ساعه": Unit.HOUR,
    "يوم": Unit.DAY,
    "اسبوع": Unit.WEEK,
    "شهر": Unit.MONTH,
    "سنه": Unit.YEAR,
    "عام": Unit.YEAR,
}
_DUAL_NOUNS: dict[str, Unit] = {
    **dict.fromkeys(("ساعتان", "ساعتين"), Unit.HOUR),
    **dict.fromkeys(("يومان", "يومين"), Unit.DAY),
    **dict.fromkeys(("اسبوعان", "اسبوعين"), Unit.WEEK),
    **dict.fromkeys(("شهران", "شهرين"), Unit.MONTH),
    **dict.fromkeys(("سنتان", "سنتين", "عامان", "عامين"), Unit.YEAR),
}
_FRACTIONS = {"نصف": 0.5, "ربع": 0.25}
_ADDED_FRACTIONS = {"ونصف": 0.5, "وربع": 0.25}
_PERCENT_SIGN = "%"
_PERCENT_WORDS = ("بالمائه", "بالمئه")
_PERCENT_PHRASES = (("في", "المائه"), ("في", "المئه"), ("من", "المائه"), ("من", "المئه"))
# Clitics a number word or unit noun may carry: "بتسعين", "لمدة", "الستين".
_PREFIXES = ("وبال", "وال", "بال", "لل", "ال", "وب", "ول", "ب", "ل", "و", "ك", "")

_TOKEN = re.compile(r"\d+(?:\.\d+)?|[^\W\d_]+|\S")
_DIGITS = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True, slots=True)
class _Token:
    text: str
    start: int
    end: int


def _tokenize(folded: str) -> list[_Token]:
    return [_Token(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(folded)]


def _strip_prefix(word: str, table: dict[str, int] | dict[str, Unit]) -> str | None:
    for prefix in _PREFIXES:
        if word.startswith(prefix) and word[len(prefix) :] in table:
            return word[len(prefix) :]
    return None


# ------------------------------------------------------------------ number words


@dataclass(frozen=True, slots=True)
class _Number:
    value: float
    start: int  # token index of the first token
    end: int  # token index just past the last token


def _parse_words(tokens: Sequence[_Token], i: int) -> _Number | None:
    """Parse a compound number in words starting at token ``i``.

    Arabic adds the parts of a compound in a fixed order, hundreds first, then
    units (or a teen), then tens: ``مائة وخمسة وعشرون`` is 100 + 5 + 20. Each
    later part is joined with ``و``. The grammar below accepts exactly that
    order, so two separate numbers (``خمسة ... وثلاثة``) are never merged.
    """
    first = tokens[i].text
    # `unit` is the last units word read; a teen marker or "مائة" may follow it.
    unit = 0
    if (word := _strip_prefix(first, _HUNDREDS)) is not None:
        total, stage = _HUNDREDS[word], "hundred"
    elif (word := _strip_prefix(first, _TENS)) is not None:
        total, stage = _TENS[word], "ten"
    elif (word := _strip_prefix(first, _UNITS)) is not None:
        total = unit = _UNITS[word]
        stage = "unit"
    elif _strip_prefix(first, dict.fromkeys(_TEEN_ONE, 1)) is not None:
        total = unit = 1
        stage = "teen-one"
    else:
        return None
    j = i + 1
    while j < len(tokens):
        step = _next_part(tokens[j].text, stage, unit, total)
        if step is None:
            break
        total, stage, unit = step
        j += 1
    if stage == "teen-one":
        return None
    return _Number(float(total), i, j)


_MAX_UNIT = 9
_MIN_HUNDRED_MULTIPLIER = 3  # "مائتان" is one word; "ثلاث مائة" is the first split form


def _next_part(word: str, stage: str, unit: int, total: int) -> tuple[int, str, int] | None:
    """Fold one more word into a compound number, or ``None`` if it ends here."""
    if stage in {"unit", "teen-one"} and word in _TEEN_MARKER and unit <= _MAX_UNIT:
        return total + 10, "teen", 0
    if (
        stage == "unit"
        and word in _HUNDRED_MULTIPLIER
        and total == unit
        and _MIN_HUNDRED_MULTIPLIER <= unit <= _MAX_UNIT
    ):
        return unit * 100, "hundred", 0
    if word.startswith("و") and stage in {"hundred", "unit"}:
        return _joined_part(word[1:], stage, unit, total)
    return None


def _joined_part(rest: str, stage: str, unit: int, total: int) -> tuple[int, str, int] | None:
    """A part joined with ``و``: units or a teen after hundreds, tens after either."""
    if stage == "hundred" and rest in _UNITS:
        return total + _UNITS[rest], "unit", _UNITS[rest]
    if stage == "hundred" and rest in _TEEN_ONE:
        return total + 1, "teen-one", 1
    if rest in _TENS and (stage == "hundred" or unit <= _MAX_UNIT):
        return total + _TENS[rest], "ten", 0
    return None


def _parse_numeral(tokens: Sequence[_Token], i: int) -> _Number | None:
    """Digits or number words at token ``i``, optionally inside parentheses."""
    j = i
    opened = tokens[j].text == "(" and j + 1 < len(tokens)
    if opened:
        j += 1
    if _DIGITS.fullmatch(tokens[j].text):
        number = _Number(float(tokens[j].text), j, j + 1)
    else:
        parsed = _parse_words(tokens, j)
        if parsed is None:
            return None
        number = parsed
    end = number.end
    if opened:
        if end >= len(tokens) or tokens[end].text != ")":
            return None
        end += 1
    return _Number(number.value, i, end)


# --------------------------------------------------------------------- extraction


def extract_quantities(text: str) -> list[Quantity]:
    """Every quantity stated in ``text``, in order of appearance.

    Args:
        text: Display or normalized Arabic; diacritics, tatweel and
            Arabic-Indic digits are handled.

    Returns:
        One `Quantity` per number-with-unit. A number written twice
        (``ستين (60) يوماً``) yields one quantity per distinct value, so an
        internally inconsistent clause shows up as two values.

    Example:
        >>> [(q.value, q.unit.value) for q in extract_quantities("لمدة (مائة وثمانين) يوماً")]
        [(180.0, 'day')]
    """
    folded = fold(text)
    tokens = _tokenize(folded.text)
    found: list[Quantity] = []
    i = 0
    while i < len(tokens):
        quantities, next_i = _quantities_at(tokens, i)
        for value, unit, first, last in quantities:
            start, end = folded.span(tokens[first].start, tokens[last - 1].end)
            found.append(Quantity(value, unit, start, end))
        i = next_i
    return found


_Match = tuple[float, Unit, int, int]  # value, unit, first token, end token


def _quantities_at(tokens: Sequence[_Token], i: int) -> tuple[list[_Match], int]:
    """Quantities starting at token ``i`` and the token index to resume from."""
    current = tokens[i].text
    if current == _PERCENT_SIGN and i + 1 < len(tokens) and _DIGITS.fullmatch(tokens[i + 1].text):
        # Right-to-left typing often puts the sign first: "%50".
        return [(float(tokens[i + 1].text), Unit.PERCENT, i, i + 2)], i + 2
    if (dual := _strip_prefix(current, _DUAL_NOUNS)) is not None:
        total, end = _add_fraction(tokens, i + 1, 2.0)
        return [(total, _DUAL_NOUNS[dual], i, end)], end
    if (singular := _strip_prefix(current, _SINGULAR_NOUNS)) is not None:
        return _singular_quantity(tokens, i, _SINGULAR_NOUNS[singular])
    for word, fraction in _FRACTIONS.items():
        if _strip_prefix(current, {word: 0}) is not None and i + 1 < len(tokens):
            unit_match = _unit_at(tokens, i + 1)
            if unit_match is not None:
                return [(fraction, unit_match[0], i, unit_match[1])], unit_match[1]
    return _numeral_quantities(tokens, i)


def _singular_quantity(tokens: Sequence[_Token], i: int, unit: Unit) -> tuple[list[_Match], int]:
    """``شهر واحد`` or ``ساعة ونصف``; a bare singular is not a count.

    ``شهر رمضان`` and ``في اليوم`` name a unit without counting it, so only an
    explicit ``واحد`` or a trailing fraction turns a singular into a quantity.
    """
    end = i + 1
    if end < len(tokens) and tokens[end].text in _UNIT_WORDS[1]:
        return [(1.0, unit, i, end + 1)], end + 1
    if end < len(tokens) and tokens[end].text in _ADDED_FRACTIONS:
        total, end = _add_fraction(tokens, end, 1.0)
        return [(total, unit, i, end)], end
    return [], end


def _numeral_quantities(tokens: Sequence[_Token], i: int) -> tuple[list[_Match], int]:
    number = _parse_numeral(tokens, i)
    if number is None:
        return [], i + 1
    values = [number.value]
    j = number.end
    # The law and many contracts repeat the number: "ستين (60) يوماً".
    if j < len(tokens) and tokens[j].text == "(":
        repeat = _parse_numeral(tokens, j)
        if repeat is not None:
            values.append(repeat.value)
            j = repeat.end
    unit_match = _unit_at(tokens, j)
    if unit_match is None:
        return [], number.end
    unit, end = unit_match
    matches: list[_Match] = []
    for value in dict.fromkeys(values):
        total, end = _add_fraction(tokens, unit_match[1], value)
        matches.append((total, unit, i, end))
    return matches, end


def _unit_at(tokens: Sequence[_Token], j: int) -> tuple[Unit, int] | None:
    """The unit starting at token ``j`` and the index after it, if any."""
    if j >= len(tokens):
        return None
    current = tokens[j].text
    if current == _PERCENT_SIGN or current in _PERCENT_WORDS:
        return Unit.PERCENT, j + 1
    if j + 1 < len(tokens) and (current, tokens[j + 1].text) in _PERCENT_PHRASES:
        return Unit.PERCENT, j + 2
    # No clitics here: in "المادة 75 وعام 2024" the "و" starts a new phrase,
    # so "وعام" must not turn 75 into years.
    if current in _UNIT_NOUNS:
        return _UNIT_NOUNS[current], j + 1
    return None


def _add_fraction(tokens: Sequence[_Token], j: int, value: float) -> tuple[float, int]:
    """Add a trailing ``ونصف`` / ``وربع`` (``ثلاثة أشهر ونصف``)."""
    if j < len(tokens) and tokens[j].text in _ADDED_FRACTIONS:
        return value + _ADDED_FRACTIONS[tokens[j].text], j + 1
    return value, j


# ---------------------------------------------------------------------- conversion

# Conversions that hold by definition.
_EXACT_FACTORS = {(Unit.WEEK, Unit.DAY): 7.0, (Unit.YEAR, Unit.MONTH): 12.0}
# Calendar units in days, as (shortest, longest). A month is 28 to 31 days; a
# year is 354 (Hijri) to 366 days, because Saudi contracts use either calendar.
_DAY_BOUNDS = {
    Unit.DAY: (1.0, 1.0),
    Unit.WEEK: (7.0, 7.0),
    Unit.MONTH: (28.0, 31.0),
    Unit.YEAR: (354.0, 366.0),
}


def convert(value: float, source: Unit, target: Unit) -> tuple[float, float] | None:
    """Express ``value`` ``source`` units in ``target`` units, as a (low, high) range.

    Exact conversions (weeks to days, years to months) give a single point.
    Calendar conversions that depend on the month or the calendar give the
    full range, so a caller can decide only when both ends agree. Hours and
    percentages convert to nothing else: a working day is not 24 hours.

    Returns:
        ``(low, high)``, or ``None`` if the units are not comparable.

    Example:
        >>> convert(6, Unit.MONTH, Unit.DAY)
        (168.0, 186.0)
    """
    if source == target:
        return value, value
    if (source, target) in _EXACT_FACTORS:
        exact = value * _EXACT_FACTORS[source, target]
        return exact, exact
    if (target, source) in _EXACT_FACTORS:
        exact = value / _EXACT_FACTORS[target, source]
        return exact, exact
    if source in _DAY_BOUNDS and target in _DAY_BOUNDS:
        source_low, source_high = _DAY_BOUNDS[source]
        target_low, target_high = _DAY_BOUNDS[target]
        return value * source_low / target_high, value * source_high / target_low
    return None


# ----------------------------------------------------------------------- matching


def iter_folded_matches(folded: str, phrases: Sequence[str]) -> Iterator[tuple[int, int]]:
    """Spans in ``folded`` where any of ``phrases`` occurs as whole words.

    A phrase may carry the clitics Arabic attaches to a word (``و``, ``ب``,
    ``ل``, ``ال``), so ``تجربه`` also matches ``والتجربه``, and each later word
    may take ``ال``; it must end at a word boundary, so ``حج`` does not match
    ``حجز``.

    Args:
        folded: Text already passed through `fold` (or `normalize_arabic`).
        phrases: Display or folded Arabic; each is folded before matching.
    """
    for phrase in phrases:
        for match in _phrase_pattern(phrase).finditer(folded):
            yield match.start(), match.end()


@cache
def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    # Memoized: rule cues are a small fixed set matched against every clause.
    # Later words may take the article too: "إجازة سنوية" matches "الإجازة السنوية".
    words = r"\s+(?:ال)?".join(re.escape(word) for word in normalize_arabic(phrase).split())
    return re.compile(r"(?<!\w)(?:[وف]?(?:بال|لل|ال|ب|ل|ك)?)" + words + r"(?!\w)")
