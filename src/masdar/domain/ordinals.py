"""Parse Arabic ordinal article headings into numbers.

Saudi laws number their articles in words, e.g. ``المادة الخامسة والأربعون بعد
المائتين`` is article 245. Amendments add "bis" articles (``التاسعة والسبعين
مكرر``) and sometimes renumber them (``(المادة الحادية والثلاثون بعد المائتين
حالياً) (المادة الأربعون بعد المائتين سابقاً)``).

Arabic composes these numbers additively: units, an optional ``عشر/عشرة`` for
11-19, tens joined with ``و``, and hundreds joined with ``بعد``. Summing the
value of each word therefore gives the number. Matching runs on normalized text
so spelling variants (``المائة`` / ``المئة``, with or without hamza) agree.
"""

import re
from dataclasses import dataclass

from masdar.domain.arabic import normalize_arabic
from masdar.domain.errors import ArticleHeadingError

_UNITS = {
    1: ("الاولي", "الاول", "الحاديه", "الحادي"),
    2: ("الثانيه", "الثاني"),
    3: ("الثالثه", "الثالث"),
    4: ("الرابعه", "الرابع"),
    5: ("الخامسه", "الخامس"),
    6: ("السادسه", "السادس"),
    7: ("السابعه", "السابع"),
    8: ("الثامنه", "الثامن"),
    9: ("التاسعه", "التاسع"),
    10: ("العاشره", "العاشر"),
}
_TENS = {
    20: ("العشرون", "العشرين"),
    30: ("الثلاثون", "الثلاثين"),
    40: ("الاربعون", "الاربعين"),
    50: ("الخمسون", "الخمسين"),
    60: ("الستون", "الستين"),
    70: ("السبعون", "السبعين"),
    80: ("الثمانون", "الثمانين"),
    90: ("التسعون", "التسعين"),
}
_HUNDREDS = {
    100: ("المائه", "المئه"),
    200: ("المائتان", "المائتين", "المئتان", "المئتين"),
    300: ("الثلاثمائه", "الثلاثمئه"),
    400: ("الاربعمائه", "الاربعمئه"),
}
_TEEN_MARKER = ("عشره", "عشر")
_WORD_VALUES: dict[str, int] = {
    word: value
    for table in (_UNITS, _TENS, _HUNDREDS)
    for value, words in table.items()
    for word in words
} | dict.fromkeys(_TEEN_MARKER, 10)

_IGNORED = {"الماده", "بعد"}
_BIS = "مكرر"
_CURRENTLY = "حاليا"
_NON_LETTERS = re.compile(r"[^\w\s]")


@dataclass(frozen=True, slots=True, order=True)
class ArticleNumber:
    """An article's official number.

    Attributes:
        value: The number, e.g. ``79``.
        bis: True for an inserted "مكرر" article (79 bis follows 79).
    """

    value: int
    bis: bool = False

    @property
    def slug(self) -> str:
        """Stable identifier fragment, e.g. ``"79"`` or ``"79-bis"``."""
        return f"{self.value}-bis" if self.bis else str(self.value)


def parse_article_number(heading: str) -> ArticleNumber:
    """Parse an article heading such as ``"المادة الخامسة والأربعون بعد المائتين :"``.

    Handles a trailing title after a colon (``المادة الأولى: التعريفات``), a
    missing ``المادة`` prefix, ``مكرر`` (bis), and renumbered headings, where
    the number marked ``حالياً`` (currently) wins over the one marked
    ``سابقاً`` (formerly).

    Args:
        heading: The heading exactly as published.

    Returns:
        The parsed `ArticleNumber`.

    Raises:
        ArticleHeadingError: If the heading contains no number or an unknown word.

    Example:
        >>> parse_article_number("( التاسعة والسبعين مكرر )")
        ArticleNumber(value=79, bis=True)
    """
    text = normalize_arabic(heading)
    if _CURRENTLY in text:
        text = text.split(_CURRENTLY, 1)[0]
    text = text.split(":", 1)[0]
    tokens = _NON_LETTERS.sub(" ", text).split()

    total, bis = 0, False
    for token in tokens:
        if token in _IGNORED:
            continue
        if token == _BIS:
            bis = True
            continue
        total += _word_value(token, heading)
    if total == 0:
        raise ArticleHeadingError(f"No article number found in heading {heading!r}")
    return ArticleNumber(total, bis)


def _word_value(token: str, heading: str) -> int:
    if token in _WORD_VALUES:
        return _WORD_VALUES[token]
    # "و" joins number words: "والاربعون" is "و" + "الاربعون".
    if token.startswith("و") and token[1:] in _WORD_VALUES:
        return _WORD_VALUES[token[1:]]
    raise ArticleHeadingError(f"Unknown number word {token!r} in heading {heading!r}")
