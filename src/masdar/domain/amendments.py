"""Amendments: how a published article becomes the text in force.

The official portal publishes each law in its *original* wording and attaches
every later amendment as a free-text note (``تم تعديل هذه المادة ... لتكون
بالنص الآتي: "..."``). Serving the original wording would give compliance teams
outdated law, so Masdar reads the notes and derives the text in force.

Only amendments whose effect is unambiguous are applied automatically: a full
replacement of the article, an added article, a repeal, a renumbering, or a
consolidation of several articles into fewer. Anything partial (one paragraph,
one word) marks the article ``REVIEW_NEEDED``: the last certain text is kept and
the note travels with it, so nobody mistakes it for verified current law.
See ADR-0005.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from masdar.domain.arabic import normalize_arabic
from masdar.domain.errors import ArticleHeadingError, InvalidDomainObjectError
from masdar.domain.ordinals import ArticleNumber, parse_article_number

_MIN_YEAR, _MAX_YEAR = 1300, 1600
_MONTHS_PER_YEAR, _MAX_DAY = 12, 30


@dataclass(frozen=True, slots=True, order=True)
class HijriDate:
    """A date in the Hijri calendar, used to order amendments."""

    year: int
    month: int
    day: int

    def __post_init__(self) -> None:
        """Reject impossible dates, which would mean the note was misread."""
        valid = (
            _MIN_YEAR <= self.year <= _MAX_YEAR
            and 1 <= self.month <= _MONTHS_PER_YEAR
            and 1 <= self.day <= _MAX_DAY
        )
        if not valid:
            raise InvalidDomainObjectError(f"Invalid Hijri date {self}")

    def __str__(self) -> str:
        """Format as ``1446/02/08``."""
        return f"{self.year}/{self.month:02d}/{self.day:02d}"


class AmendmentKind(StrEnum):
    """What an amendment note does to the article it is attached to."""

    REPLACE = "replace"  # the whole article gets new text
    ADD = "add"  # a new article is added (possibly a different one)
    REPEAL = "repeal"  # the article (or its whole part/chapter) is repealed
    RENUMBER = "renumber"  # the article moves to a new number, text unchanged
    CONSOLIDATE = "consolidate"  # several articles are redrafted into fewer
    PARTIAL = "partial"  # a paragraph/word changes; not applied automatically


class ArticleStatus(StrEnum):
    """How trustworthy an article's text is as current law."""

    IN_FORCE = "in_force"  # never amended
    AMENDED = "amended"  # amendments applied automatically, provenance kept
    REVIEW_NEEDED = "review_needed"  # a partial amendment is not yet applied
    REPEALED = "repealed"  # no longer in force
    SUPERSEDED = "superseded"  # replaced by a consolidation; its number is reused


@dataclass(frozen=True, slots=True)
class Amendment:
    """One amendment note, parsed.

    Attributes:
        kind: What the amendment does.
        note: The note exactly as published.
        decree: Royal decree reference, e.g. ``"م/44"``.
        issued: Date of the decree.
        effective: Date it takes effect, when the note states one.
        new_text: The quoted new wording, when the note carries one.
        target: For ``ADD``, the number of the added article.
        target_label: For ``ADD``, the added article's number as written,
            e.g. ``"الحادية عشرة مكرر"``.
        consolidated: For ``CONSOLIDATE``, the articles that were redrafted.
    """

    kind: AmendmentKind
    note: str
    decree: str | None = None
    issued: HijriDate | None = None
    effective: HijriDate | None = None
    new_text: str | None = None
    target: ArticleNumber | None = None
    target_label: str | None = None
    consolidated: tuple[ArticleNumber, ...] = ()


# Patterns run on the normalized *preamble* of a note: the text before the
# quoted new wording. Matching the quote itself would let words inside the new
# law text (e.g. "إلغاء الفصل") change how the note is classified.
_REPEAL = re.compile(r"(الغيت|حذفت|الغاء) هذه الماده|الغاء (الباب|الفصل)")
_ADD = re.compile(r"(اضيفت|اضافه) (هذه الماده|ماده)")
_CONSOLIDATE = re.compile(r"تعديل احكام (المواد|المادتين).{0,600}?اعاده صياغ")
_REPLACE = re.compile(r"(عدلت|تعديل) هذه الماده.{0,120}?(لتكون|ليكون|وتكون|بالنص الاتي)")
# "عُدلت هذه المادة على النحو الآتي: - عُدل صدرها ... - عُدلت الفقرة ..." lists
# several partial edits; it must never be mistaken for one full replacement.
_EDIT_LIST = re.compile(r"علي النحو الاتي")  # normalized: على -> علي
_RENUMBER = re.compile(r"نقلها لتكون")
_DECREE = re.compile(r"\(\s*م\s*/\s*(\d+)\s*\)")
_DATE = re.compile(r"(\d{1,4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,4})")
_ISSUED_DATE = re.compile(r"[وب]تاريخ\s*" + _DATE.pattern)
_EFFECTIVE_DATE = re.compile(r"يعمل بها من تاريخ\s*" + _DATE.pattern)
_TARGET = re.compile(r"(?:تحمل الرقم|ترتيبها)\s*\(([^)]+)\)")
_PARENTHESIZED = re.compile(r"\(([^)]+)\)")

# Quotes are found in the *original* note (normalization would shift offsets).
_QUOTE_OPEN = re.compile(r"(?:الآتي|الاتي|لتكون|ليكون|وتكون)\s*:?\s*([\"“«])")
_QUOTE_CLOSE = {'"': '"', "“": "”", "«": "»"}
_FOUR_DIGIT_YEAR = 4

# A heading inside quoted text: "المادة <number words> :". The tempered token
# stops a match at a second "المادة" or at punctuation, so a reference in the
# previous article's body ("أحكام المادة الرابعة عشرة السابقة.") cannot
# swallow the next heading.
_INNER_HEADING = re.compile(r"المادة\s+((?:(?!المادة)[^:\n.،؛]){3,80}?)\s*:")


def parse_amendment(note: str) -> Amendment:
    """Classify an amendment note and extract its decree, dates and new text.

    Args:
        note: One amendment note as published.

    Returns:
        The parsed `Amendment`. Unrecognized notes are ``PARTIAL``, which is
        the safe default: they are never applied automatically.
    """
    outside = normalize_arabic(_outside_quote(note))
    new_text = extract_quoted_text(note)
    kind = _classify(outside, has_new_text=new_text is not None)
    target, target_label = _target(note) if kind is AmendmentKind.ADD else (None, None)
    return Amendment(
        kind=kind,
        note=note,
        decree=_decree(outside),
        issued=_date(_ISSUED_DATE, outside),
        effective=_date(_EFFECTIVE_DATE, outside),
        new_text=new_text,
        target=target,
        target_label=target_label,
        consolidated=_consolidated(note) if kind is AmendmentKind.CONSOLIDATE else (),
    )


def _outside_quote(note: str) -> str:
    """The note without its quoted new wording: the preamble plus any tail.

    The decree and date may come before the quote or after it ("... ."
    وأضيفت هذه المادة بموجب المرسوم ... وتاريخ ...), but never inside it.
    """
    opening = _QUOTE_OPEN.search(note)
    if opening is None:
        return note
    end = note.rfind(_QUOTE_CLOSE[opening.group(1)])
    tail = note[end + 1 :] if end > opening.end() else ""
    return f"{note[: opening.end()]} {tail}"


def _classify(preamble: str, *, has_new_text: bool) -> AmendmentKind:
    if _REPEAL.search(preamble):
        return AmendmentKind.REPEAL
    if _ADD.search(preamble) and has_new_text:
        return AmendmentKind.ADD
    if _CONSOLIDATE.search(preamble) and has_new_text:
        return AmendmentKind.CONSOLIDATE
    if _REPLACE.search(preamble) and has_new_text and not _EDIT_LIST.search(preamble):
        return AmendmentKind.REPLACE
    if _RENUMBER.search(preamble):
        return AmendmentKind.RENUMBER
    return AmendmentKind.PARTIAL


def extract_quoted_text(note: str) -> str | None:
    """Return the quoted new wording that follows "بالنص الآتي:" and similar.

    The quote runs from the opening mark after the keyword to the *last*
    matching closing mark, so quotation marks inside the new text survive.

    Example:
        >>> extract_quoted_text('عدلت هذه المادة لتكون بالنص الآتي: "يُعد طلب الاستقالة مقبولاً".')
        'يُعد طلب الاستقالة مقبولاً'
    """
    opening = _QUOTE_OPEN.search(note)
    if opening is None:
        return None
    start = opening.end()
    end = note.rfind(_QUOTE_CLOSE[opening.group(1)])
    if end <= start:
        return None
    text = note[start:end].strip()
    return text or None


def _decree(normalized: str) -> str | None:
    match = _DECREE.search(normalized)
    return f"م/{match.group(1)}" if match else None


def _date(pattern: re.Pattern[str], normalized: str) -> HijriDate | None:
    match = pattern.search(normalized)
    if match is None:
        return None
    first, month, last = match.groups()
    # Notes mix "1446/2/8" (year first) and "5 / 6 / 1436" (day first).
    year, day = (first, last) if len(first) == _FOUR_DIGIT_YEAR else (last, first)
    try:
        return HijriDate(int(year), int(month), int(day))
    except InvalidDomainObjectError:
        return None


def _target(note: str) -> tuple[ArticleNumber | None, str | None]:
    match = _TARGET.search(note)
    if match is None:
        return None, None
    label = " ".join(match.group(1).split())
    try:
        return parse_article_number(label), label
    except ArticleHeadingError:
        return None, None


def _consolidated(note: str) -> tuple[ArticleNumber, ...]:
    """Article numbers listed in parentheses before the quoted new text."""
    preamble = note.split("على النحو", 1)[0]
    numbers: list[ArticleNumber] = []
    for group in _PARENTHESIZED.findall(preamble):
        try:
            number = parse_article_number(group)
        except ArticleHeadingError:
            continue  # e.g. "( م/ 46)"
        if number not in numbers:
            numbers.append(number)
    return tuple(numbers)


@dataclass(frozen=True, slots=True)
class Resolution:
    """The outcome of applying an article's own amendments in date order."""

    status: ArticleStatus
    text: str


def resolve(
    number: ArticleNumber, original_text: str, amendments: tuple[Amendment, ...]
) -> Resolution:
    """Apply the amendments attached to article ``number``, oldest decree first.

    An ``ADD`` note that creates a *different* article does not touch this one
    (the builder creates that article). A ``CONSOLIDATE`` note either gives this
    article its slice of the redrafted text or, if the article was folded into
    others, marks it ``SUPERSEDED``.

    Args:
        number: The article's own number.
        original_text: The article as originally published.
        amendments: Amendments attached to this article.

    Returns:
        The resulting status and text.
    """
    status, text = ArticleStatus.IN_FORCE, original_text
    # sorted() is stable: notes with the same decree date keep their published
    # order, which on the portal is oldest first.
    for amendment in sorted(amendments, key=_chronological):
        status, text = _apply(number, status, text, amendment)
    if status is ArticleStatus.AMENDED and _order_is_uncertain(amendments):
        status = ArticleStatus.REVIEW_NEEDED
    return Resolution(status, text)


def _order_is_uncertain(amendments: tuple[Amendment, ...]) -> bool:
    """Several full texts, at least one undated: which one is current is unknown."""
    full_texts = [a for a in amendments if a.new_text and a.kind is not AmendmentKind.PARTIAL]
    return len(full_texts) > 1 and any(a.issued is None for a in full_texts)


def split_consolidated_text(
    text: str, numbers: tuple[ArticleNumber, ...]
) -> dict[ArticleNumber, str]:
    """Split a consolidation's quoted text into the redrafted articles.

    The quote reads ``"المادة التاسعة والعشرون بعد المائتين : ... المادة
    الثلاثون بعد المائتين : ..."``. A heading counts only if it parses as one of
    the consolidated ``numbers``, so references inside the body ("أحكام المادة
    الثلاثين") are not mistaken for headings.
    """
    starts: list[tuple[int, int, ArticleNumber]] = []
    for match in _INNER_HEADING.finditer(text):
        try:
            number = parse_article_number(match.group(1))
        except ArticleHeadingError:
            continue
        if number in numbers:
            starts.append((match.start(), match.end(), number))
    slices: dict[ArticleNumber, str] = {}
    for index, (_, body_start, number) in enumerate(starts):
        body_end = starts[index + 1][0] if index + 1 < len(starts) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            slices[number] = body
    return slices


def _chronological(amendment: Amendment) -> tuple[bool, HijriDate]:
    # Undated notes keep their published order, after the dated ones.
    return amendment.issued is None, amendment.issued or HijriDate(_MIN_YEAR, 1, 1)


# Once an article is repealed or superseded, a later partial edit cannot bring it
# back; only a full new text (replace/add/consolidate) can.
_TERMINAL = frozenset({ArticleStatus.REPEALED, ArticleStatus.SUPERSEDED})


def _apply(
    number: ArticleNumber, status: ArticleStatus, text: str, amendment: Amendment
) -> tuple[ArticleStatus, str]:
    kind = amendment.kind
    new_text = _strip_own_heading(amendment.new_text, number) if amendment.new_text else None
    if kind is AmendmentKind.REPEAL:
        return ArticleStatus.REPEALED, text
    if kind is AmendmentKind.REPLACE and new_text:
        return ArticleStatus.AMENDED, new_text
    if kind is AmendmentKind.ADD and new_text and amendment.target in (None, number):
        return ArticleStatus.AMENDED, new_text
    if kind is AmendmentKind.CONSOLIDATE and amendment.new_text:
        return _apply_consolidation(number, status, text, amendment, amendment.new_text)
    if kind is AmendmentKind.PARTIAL and status not in _TERMINAL:
        return ArticleStatus.REVIEW_NEEDED, text
    return status, text


def _strip_own_heading(text: str, number: ArticleNumber) -> str:
    """Drop a leading ``المادة ... :`` heading when it names this same article."""
    match = _INNER_HEADING.match(text)
    if match is None:
        return text
    try:
        heading_number = parse_article_number(match.group(1))
    except ArticleHeadingError:
        return text
    stripped = text[match.end() :].strip()
    return stripped if heading_number == number and stripped else text


def _apply_consolidation(
    number: ArticleNumber,
    status: ArticleStatus,
    text: str,
    amendment: Amendment,
    new_text: str,
) -> tuple[ArticleStatus, str]:
    slices = split_consolidated_text(new_text, amendment.consolidated)
    if number in slices:
        return ArticleStatus.AMENDED, slices[number]
    if slices and number in amendment.consolidated:
        return ArticleStatus.SUPERSEDED, text
    # The redrafted text could not be split reliably: flag it, never guess.
    return (status if status in _TERMINAL else ArticleStatus.REVIEW_NEEDED), text
