"""Check contract clauses against quantitative limits of the law, as code.

A `Rule` says, for one article of the law in force, which words make a clause
about its topic (cues), which units it can be compared in, and the limit. For
each clause the checker finds the quantities stated near the cues and returns a
`Finding`: violation, compliant, or review needed. There is no model and no
API: the same clause always gives the same answer, with the article to cite.

Matching is conservative on purpose (ADR-0010). A wrong "violation" on a real
contract is worse than "review needed", so the checker decides only when the
evidence leaves no doubt:

* a rule fires only when its cues are present and a quantity of a compatible
  unit is stated near them;
* inexact conversions (months to days) decide only when the whole range of
  possible values falls on one side of the limit;
* conflicting values, a missing condition the limit depends on, a nearby legal
  exception, or an article whose text in force is itself under review
  (ADR-0005) all give `FindingKind.REVIEW_NEEDED`.
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from masdar.domain.amendments import ArticleStatus
from masdar.domain.arabic import normalize_arabic
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.quantities import (
    FoldedText,
    Quantity,
    Unit,
    convert,
    extract_quantities,
    fold,
    iter_folded_matches,
)
from masdar.domain.search import MAX_QUERY_CHARS, ArticleResult


class FindingKind(StrEnum):
    """The verdict on one rule for one clause."""

    VIOLATION = "violation"
    COMPLIANT = "compliant"
    REVIEW_NEEDED = "review_needed"


class Comparator(StrEnum):
    """Whether the law sets a ceiling or a floor."""

    MAXIMUM = "maximum"
    MINIMUM = "minimum"


class ReviewReason(StrEnum):
    """Why the checker declined to decide."""

    INEXACT_CONVERSION = "inexact_conversion"
    CONFLICTING_VALUES = "conflicting_values"
    OPEN_TOTAL = "open_total"
    CONDITION_NOT_STATED = "condition_not_stated"
    POSSIBLE_EXCEPTION = "possible_exception"
    UNCLEAR_ROLE = "unclear_role"
    CONDITION_CONTRADICTED = "condition_contradicted"
    ARTICLE_UNDER_REVIEW = "article_under_review"


_REASON_TEXT = {
    ReviewReason.INEXACT_CONVERSION: (
        "تحويل المدة إلى وحدة النظام غير دقيق (الشهر 28 إلى 31 يوماً، والسنة 354 إلى 366 يوماً)"
    ),
    ReviewReason.CONFLICTING_VALUES: "يذكر البند أكثر من قيمة ولا تتفق نتائجها",
    ReviewReason.OPEN_TOTAL: "يسمح البند بالتمديد دون أن يحدد المجموع",
    ReviewReason.CONDITION_NOT_STATED: "لا يذكر البند الشرط الذي يتوقف عليه تطبيق الحد",
    ReviewReason.POSSIBLE_EXCEPTION: "قد ينطبق استثناء نص عليه النظام",
    ReviewReason.UNCLEAR_ROLE: (
        "لا تدل صياغة البند بوضوح على أن هذا الرقم هو المقدار الذي يحدده النظام"
    ),
    ReviewReason.CONDITION_CONTRADICTED: (
        "المدة ضمن الحد، لكن البند يذكر ما قد يخالف شرطاً آخر في المادة (مثل الأجر الكامل)"
    ),
    ReviewReason.ARTICLE_UNDER_REVIEW: (
        "نص المادة النافذ قيد المراجعة لأن تعديلاً جزئياً عليها لم يُطبق آلياً"
    ),
}

# How far (in characters) a quantity may be from a topic cue and still belong
# to it; about one contract sentence.
CUE_WINDOW = 80
# How far after a quantity a rate word ("يومياً") may appear.
RATE_WINDOW = 30
# How far before a quantity a qualifier ("بعد مرور", "لا يتجاوز") may appear.
LEAD_WINDOW = 40

_CAP_PHRASES = (
    "لا يتجاوز",
    "لا تتجاوز",
    "لا يزيد",
    "لا تزيد",
    "ألا يتجاوز",
    "ألا تتجاوز",
    "ألا يزيد",
    "ألا تزيد",
    "بحد أقصى",
    "حد أقصى",
    "مجموع",
    "مجموعها",
    "إجمالي",
)
# A total stated after the number: "180 يوماً كحد أقصى شاملة أي تمديد".
_CAP_AFTER_PHRASES = (
    "كحد أقصى",
    "حداً أقصى",
    "بحد أقصى",
    "حد أقصى",
    "شاملة",
    "شاملاً",
    "بما في ذلك",
    "بما فيها",
)
_EXTENSION_PHRASES = (
    "تمديد",
    "تمديدها",
    "تمديده",
    "التمديد",
    "يمدد",
    "تمدد",
    "نمدد",
    "يمددها",
    "نمددها",
    "تمددها",
    "تجديدها",
    "التجديد",
)
_SAME_LENGTH_PHRASES = ("مماثلة", "مماثله")
# Commas and sentence ends, but not the point in "7.5".
_PHRASE_BREAK = re.compile(r"[،,;؛\n]|\.(?!\d)")
# Words that may stand between a cue and the amount it states (folded forms):
# "مدتها", "لمدة", "بأجر كامل", "قبل", "لا تقل عن", and the parties.
_LINK_LINES = (
    "مدتها مدته مدة لمدة بمدة قدرها قدره تبلغ يبلغ تكون يكون هي هو",
    "مدفوعة الأجر بأجر بالأجر أجر كامل كاملاً كاملة براتب الراتب بالكامل",
    "قبل كتابي كتابياً كتابة خطي خطياً لا تقل يقل عن تزيد يزيد على",
    "من ما نسبته نسبة بنسبة راتب راتبه الشهري الأساسي أول",
    "الموظف العامل الموظفة العاملة للموظف للعامل للموظفة للعاملة",
    "الشركة المنشأة صاحب العمل الطرف الآخر الطرفين للطرف الأول الثاني لصاحب للشركة للمنشأة",
)
# Words that introduce a measure explicitly. The possessive ones ("مدتها":
# its duration) refer back to the topic just named; the open ones ("لمدة": for
# a period of) can qualify anything in the phrase ("طلب الإجازة لمدة 5 أيام"
# is a request, not the entitlement), so only ceilings accept them, where a
# misread number would have to be larger than the limit to do harm.
_OWN_MEASURE_WORDS = frozenset(
    normalize_arabic(word)
    for word in ("مدتها", "مدته", "ومدتها", "ومدته", "قدرها", "قدره", "مقدارها", "نسبته")
)
_OPEN_MEASURE_WORDS = frozenset(
    normalize_arabic(word) for word in ("لمدة", "مدة", "بمدة", "بنسبة", "نسبة")
)
_LINK_WORDS = frozenset(normalize_arabic(word) for line in _LINK_LINES for word in line.split())
_MAX_LINK_WORDS = 6
_GAP_PUNCTUATION = re.compile(r"[():\-–\"«»]")


@dataclass(frozen=True, slots=True)
class Rule:
    """One quantitative limit of the law, pinned to the article that states it.

    Attributes:
        rule_id: Stable id, e.g. ``"probation-max"``.
        article_id: The article whose text in force states the limit.
        article_heading: Its heading, for the citation in messages.
        article_status: Its status; ``REVIEW_NEEDED`` forbids a hard verdict.
        law_title: The law's title, for the citation.
        topic: What the clause states, in Arabic (``"فترة التجربة"``).
        source_phrase: The words of the text in force that state the limit.
        cues: Groups of words; every group must match the clause (any word in
            a group). The first group locates the topic: quantities must be
            within `CUE_WINDOW` of it.
        comparator: Ceiling or floor.
        limit: The limit as a quantity (its span is unused).
        units: Units a stated quantity may have; anything else is ignored.
            Each must convert to the limit's unit (`convert`).
        per: Rate words that must follow the quantity (``"يومياً"``), for
            limits per day or per week.
        excludes: Words that mean the clause is about something else.
        anchor: If set, these words must appear and only the quantity nearest
            to them is judged (``"خمس سنوات"`` for the longer leave).
        skip_after: Words that, just before a quantity, make it a condition
            rather than the amount (``"بعد مرور 6 أشهر"``).
        requires_for_violation: Groups of words the limit depends on; without
            them a would-be violation becomes review needed.
        blocks_violation: Words signalling a legal exception; with them a
            would-be violation becomes review needed.
        exception_margin: For a ceiling, values up to ``limit + margin`` are
            review needed rather than a violation (an exception may apply).
        cumulative: The law limits a total (probation): extensions add up.
        blocks_compliant: Words that contradict another condition of the
            article (``"نصف أجرها"`` against "بأجر كامل"); with them a
            would-be compliant verdict becomes review needed, because a
            number within the limit is not a clean bill on its own.
    """

    rule_id: str
    article_id: str
    article_heading: str
    article_status: ArticleStatus
    law_title: str
    topic: str
    source_phrase: str
    cues: tuple[tuple[str, ...], ...]
    comparator: Comparator
    limit: Quantity
    units: frozenset[Unit]
    per: tuple[str, ...] = ()
    excludes: tuple[str, ...] = ()
    anchor: tuple[str, ...] = ()
    skip_after: tuple[str, ...] = ()
    requires_for_violation: tuple[tuple[str, ...], ...] = ()
    blocks_violation: tuple[str, ...] = ()
    exception_margin: float = 0.0
    cumulative: bool = False
    blocks_compliant: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject rules that could never fire or never compare."""
        if not self.rule_id.strip() or ":" not in self.article_id:
            raise InvalidDomainObjectError(f"Rule needs an id and a law:article id: {self!r}")
        if not self.cues or not all(self.cues):
            raise InvalidDomainObjectError(f"Rule {self.rule_id} needs non-empty cue groups")
        if self.limit.unit not in self.units:
            raise InvalidDomainObjectError(f"Rule {self.rule_id}: the limit's unit is not accepted")
        for unit in self.units:
            if convert(1.0, unit, self.limit.unit) is None:
                raise InvalidDomainObjectError(
                    f"Rule {self.rule_id}: {unit} does not convert to {self.limit.unit}"
                )

    @property
    def law_id(self) -> str:
        """The law the rule belongs to, e.g. ``"labor-law"``."""
        return self.article_id.split(":", 1)[0]

    @property
    def citation(self) -> str:
        """Human-readable citation, e.g. ``"نظام العمل (المادة الثالثة والخمسون)"``."""
        return f"{self.law_title} ({self.article_heading})"


@dataclass(frozen=True, slots=True)
class Finding:
    """The verdict of one rule on one clause.

    Attributes:
        rule: The rule that fired.
        kind: Violation, compliant, or review needed.
        stated: The quantities of the clause the verdict rests on.
        message: Arabic explanation that cites the article.
        reason: Why the checker did not decide, for ``REVIEW_NEEDED``.
    """

    rule: Rule
    kind: FindingKind
    stated: tuple[Quantity, ...]
    message: str
    reason: ReviewReason | None = None

    @property
    def rule_id(self) -> str:
        """Id of the rule that fired."""
        return self.rule.rule_id


@dataclass(frozen=True, slots=True)
class Clause:
    """One clause of a contract or policy.

    Attributes:
        index: 1-based position in the document.
        text: The clause as written (trimmed).
        start: Offset of its first character in the document.
        end: Offset just past its last character.
    """

    index: int
    text: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class ClauseReport:
    """Findings and related articles for one clause.

    Attributes:
        clause: The clause.
        findings: One per rule that fired, in rule order.
        related: Articles of the law in force retrieved for the clause.
    """

    clause: Clause
    findings: tuple[Finding, ...]
    related: tuple[ArticleResult, ...] = ()


@dataclass(frozen=True, slots=True)
class ContractReport:
    """The whole document, clause by clause.

    Attributes:
        clauses: One report per clause, in document order.
    """

    clauses: tuple[ClauseReport, ...]

    @property
    def counts(self) -> Mapping[FindingKind, int]:
        """How many findings of each kind, every kind present (zero if none)."""
        counts = dict.fromkeys(FindingKind, 0)
        for report in self.clauses:
            for finding in report.findings:
                counts[finding.kind] += 1
        return counts

    @property
    def violations(self) -> int:
        """How many findings are violations."""
        return self.counts[FindingKind.VIOLATION]

    @property
    def review_needed(self) -> int:
        """How many findings need a person to decide."""
        return self.counts[FindingKind.REVIEW_NEEDED]

    @property
    def compliant(self) -> int:
        """How many findings are within the limit."""
        return self.counts[FindingKind.COMPLIANT]


# --------------------------------------------------------------------- splitting

_ORDINALS = "اولا|ثانيا|ثالثا|رابعا|خامسا|سادسا|سابعا|ثامنا|تاسعا|عاشرا"
_ITEM_MARKER = re.compile(
    r"\s*(?:"
    r"\(\s*\d{1,3}\s*\)"  # (1)
    r"|\d{1,3}\s*(?:[-–)\]:/]|\.(?!\d))"  # 1-  1)  1.
    r"|\(\s*[ابجدهوزحطي]\s*\)"  # (أ)
    r"|[ابجدهوزحطي]\s*[-–)]\s"  # أ-  ب)
    r"|[•●▪◦■*\-–]\s"  # bullets
    rf"|(?:البند\s+)?(?:{_ORDINALS})\b"  # أولاً، البند ثانياً
    r"|(?:البند|الماده)\s*\(?\s*[^\s:()]+\s*\)?\s*[:\-–]"  # البند الأول:  المادة (3):
    r")"
)
_SENTENCE_END = re.compile(r"[.;؛:](?=\s)")
_HAS_CONTENT = re.compile(r"[^\W_]")
# An item number alone ("1-", "(٣)") is not content.
_LEADING_NUMBER = re.compile(r"^[(\[]?\s*\d{1,3}\s*[)\]\-–.:/]?")


def split_clauses(text: str) -> list[Clause]:
    """Split a contract or policy into clauses, keeping their spans.

    Every line is a clause, and so is every numbered item, bullet or Arabic
    ordinal (``أولاً``) that starts after the end of a sentence on the same
    line. Clauses without letters or digits (a lone ``1-``) are dropped.

    Example:
        >>> [c.text for c in split_clauses("أولاً: الأجر 5000 ريال. ثانياً: التجربة 90 يوماً")]
        ['أولاً: الأجر 5000 ريال.', 'ثانياً: التجربة 90 يوماً']
    """
    folded = fold(text)
    cuts = {0, len(folded.text)}
    for line in re.finditer(r"[^\n]+", folded.text):
        cuts.update((line.start(), line.end()))
        for stop in _SENTENCE_END.finditer(folded.text, line.start(), line.end()):
            if _ITEM_MARKER.match(folded.text, stop.end(), line.end()):
                cuts.add(stop.end())
    bounds = sorted(cuts)
    clauses: list[Clause] = []
    for start, end in pairwise(bounds):
        clause = _clause(text, folded, start, end, len(clauses) + 1)
        if clause is not None:
            clauses.append(clause)
    return clauses


def _clause(text: str, folded: FoldedText, start: int, end: int, index: int) -> Clause | None:
    first, last = folded.span(start, end)
    raw = text[first:last]
    stripped = raw.strip()
    if not _HAS_CONTENT.search(_LEADING_NUMBER.sub("", stripped, count=1)):
        return None
    begin = first + (len(raw) - len(raw.lstrip()))
    return Clause(index, stripped, begin, begin + len(stripped))


def clause_query(text: str) -> str:
    """The clause cut to the longest whole-word prefix a search accepts.

    `SearchService` rejects queries longer than ``MAX_QUERY_CHARS``; the start
    of a clause carries its topic, so the tail is what gets dropped.
    """
    trimmed = " ".join(text.split())
    if len(trimmed) <= MAX_QUERY_CHARS:
        return trimmed
    head = trimmed[: MAX_QUERY_CHARS + 1]
    if " " not in head:
        return trimmed[:MAX_QUERY_CHARS]
    return head.rsplit(" ", 1)[0]


# ---------------------------------------------------------------------- checking


@dataclass(frozen=True, slots=True)
class _Context:
    """A clause prepared once for every rule."""

    text: str
    folded: FoldedText
    quantities: tuple[Quantity, ...]
    # Every rule that applies to the clause, with the spans of its topic cue.
    topics: tuple[tuple[Rule, tuple[tuple[int, int], ...]], ...] = ()

    def spans(self, phrases: Sequence[str]) -> list[tuple[int, int]]:
        """Input spans of whole-word matches of ``phrases``."""
        return [
            self.folded.span(start, end)
            for start, end in iter_folded_matches(self.folded.text, phrases)
        ]

    def has(self, phrases: Sequence[str]) -> bool:
        """True if any of ``phrases`` occurs as whole words."""
        return any(iter_folded_matches(self.folded.text, phrases))

    def before(self, quantity: Quantity, phrases: Sequence[str]) -> bool:
        """True if any of ``phrases`` occurs shortly before ``quantity`` in its phrase."""
        start = max(self.phrase_start(quantity.start), quantity.start - LEAD_WINDOW)
        lead = normalize_arabic(self.text[start : quantity.start])
        return any(iter_folded_matches(lead, phrases))

    def phrase_start(self, offset: int) -> int:
        """Offset where the phrase holding ``offset`` begins."""
        breaks = [m.end() for m in _PHRASE_BREAK.finditer(self.text, 0, offset)]
        return breaks[-1] if breaks else 0

    def same_phrase(self, quantity: Quantity, spans: Sequence[tuple[int, int]]) -> bool:
        """True if one of ``spans`` lies in the phrase holding ``quantity``."""
        phrase = self.phrase_of(quantity.start)
        return any(self.phrase_of(start) == phrase for start, _ in spans)

    def states(self, quantity: Quantity, cues: Sequence[tuple[int, int]], *, ceiling: bool) -> bool:
        """True if ``quantity`` reads as the amount a cue is about.

        That is the case when the quantity comes right after a cue with only
        linking words between ("إجازة سنوية مدتها 15 يوماً", "بإشعار كتابي قبل
        30 يوماً"), or right before one ("15 يوماً إجازة سنوية"), or when an
        explicit measure word introduces it in the cue's own phrase ("إجازة
        الحج لمرة واحدة ومدتها خمسة أيام"; for a ceiling also "بعدم منافسة
        الشركة داخل المملكة لمدة ثلاث سنوات", "بنسبة 20%"). A number in
        another role, such as a deadline, a carry-over cap or an accrual rate
        ("بواقع 2.5 يوم عن كل شهر"), is linked by other words and fails.
        """
        if self.same_phrase(quantity, cues):
            lead = normalize_arabic(
                self.text[max(0, quantity.start - LEAD_WINDOW) : quantity.start]
            )
            words = _GAP_PUNCTUATION.sub(" ", lead).split()
            if words and (
                words[-1] in _OWN_MEASURE_WORDS or (ceiling and words[-1] in _OPEN_MEASURE_WORDS)
            ):
                return True
        for start, end in cues:
            if end <= quantity.start:
                gap = normalize_arabic(self.text[end : quantity.start])
                words = _GAP_PUNCTUATION.sub(" ", gap).split()
                if len(words) <= _MAX_LINK_WORDS and all(w in _LINK_WORDS for w in words):
                    return True
            elif quantity.end <= start and not self.text[quantity.end : start].strip():
                return True
        return False

    def phrase_of(self, offset: int) -> int:
        """Index of the phrase (text between commas or sentence ends) holding ``offset``."""
        return len(_PHRASE_BREAK.findall(self.text, 0, offset))

    def after(self, quantity: Quantity, phrases: Sequence[str]) -> bool:
        """True if any of ``phrases`` starts shortly after ``quantity``.

        The window stops at the next quantity: in "40 ساعة أسبوعياً بواقع 8
        ساعات يومياً", "يومياً" belongs to the 8, not to the 40.
        """
        stop = min(
            [quantity.end + RATE_WINDOW]
            + [q.start for q in self.quantities if q.start >= quantity.end]
        )
        tail = normalize_arabic(self.text[quantity.end : stop])
        return any(iter_folded_matches(tail, phrases))

    def excluded(self, quantity: Quantity, rule: Rule) -> bool:
        """True if one of the rule's exclusion words shares the quantity's phrase.

        Scoped to the phrase, so a Ramadan sub-item does not silence the
        ordinary working day stated on the line above it.
        """
        return bool(rule.excludes) and self.same_phrase(quantity, self.spans(rule.excludes))

    def claimed_elsewhere(self, quantity: Quantity, rule: Rule, own: int) -> bool:
        """True if another applicable topic in the same phrase is strictly closer.

        A number belongs to the topic it is written next to: in "دون إشعار أو
        تعويض، ومدة التجربة 90 يوماً" the 90 days are the probation, not a
        notice period, although both cues are within reach.
        """
        return any(
            other.cues[0] != rule.cues[0]
            and quantity.unit in other.units
            and spans
            and self.same_phrase(quantity, spans)
            and _distance(quantity, spans) < own
            and not self.excluded(quantity, other)
            for other, spans in self.topics
        )


def check_clause(text: str, rules: Sequence[Rule]) -> tuple[Finding, ...]:
    """Apply every rule to one clause.

    Args:
        text: The clause.
        rules: The rules to apply.

    Returns:
        One finding per rule that fired, in rule order; usually none.
    """
    plain = _Context(text, fold(text), tuple(extract_quantities(text)))
    # Only rules that apply to this clause compete for its numbers.
    topics = tuple(
        (rule, tuple(plain.spans(rule.cues[0])))
        for rule in rules
        if all(plain.has(group) for group in rule.cues)
    )
    context = _Context(plain.text, plain.folded, plain.quantities, topics)
    findings = (_apply(rule, context) for rule in rules)
    return tuple(finding for finding in findings if finding is not None)


def _apply(rule: Rule, context: _Context) -> Finding | None:
    groups = [context.spans(group) for group in rule.cues]
    if not all(groups):
        return None
    candidates = _candidates(rule, context, groups)
    if rule.anchor and candidates:
        candidates = _nearest_to_anchor(rule, context, candidates)
    if not candidates:
        return None
    kind, reason, judged = _judge(rule, context, candidates)
    if kind is FindingKind.VIOLATION:
        kind, reason = _guard_violation(rule, context, groups, judged)
    elif (
        kind is FindingKind.COMPLIANT
        and rule.blocks_compliant
        and context.has(rule.blocks_compliant)
    ):
        kind, reason = FindingKind.REVIEW_NEEDED, ReviewReason.CONDITION_CONTRADICTED
    if rule.article_status is ArticleStatus.REVIEW_NEEDED:
        kind, reason = FindingKind.REVIEW_NEEDED, ReviewReason.ARTICLE_UNDER_REVIEW
    return Finding(rule, kind, judged, _message(rule, kind, judged, reason), reason)


def _candidates(
    rule: Rule, context: _Context, groups: Sequence[Sequence[tuple[int, int]]]
) -> list[Quantity]:
    """Quantities of an accepted unit near the topic that are not themselves cues."""
    taken = [span for group in groups for span in group]
    if rule.anchor:
        taken += context.spans(rule.anchor)
    found = [
        quantity
        for quantity in context.quantities
        if quantity.unit in rule.units
        and not any(_overlaps(quantity, span) for span in taken)
        and (own := _distance(quantity, groups[0])) <= CUE_WINDOW
        and not context.excluded(quantity, rule)
        and not context.claimed_elsewhere(quantity, rule, own)
        and (not rule.per or context.after(quantity, rule.per))
        and not (rule.skip_after and context.before(quantity, rule.skip_after))
    ]
    # Prefer numbers in a phrase that names the topic; a period's extension
    # or stated total belongs to it too ("ويجوز تمديدها 90 يوماً").
    topical = list(taken)
    if rule.cumulative:
        topical += context.spans((*_EXTENSION_PHRASES, *_CAP_PHRASES))
    own_phrase = [q for q in found if context.same_phrase(q, topical)]
    return own_phrase or found


def _nearest_to_anchor(
    rule: Rule, context: _Context, candidates: Sequence[Quantity]
) -> list[Quantity]:
    """The one quantity that belongs to the anchor, or none.

    Only quantities in the anchor's own phrase (between commas or sentence
    ends) qualify: in "خمسة أيام عند زواجه، وثلاثة أيام عند وفاة أخيه" the
    three days are closer to "زواجه" in characters but belong to the next phrase.
    """
    anchors = context.spans(rule.anchor)
    phrases = {context.phrase_of(start) for start, _ in anchors}
    own = [q for q in candidates if context.phrase_of(q.start) in phrases]
    if not own:
        return []
    return [min(own, key=lambda q: _distance(q, anchors))]


def _judge(
    rule: Rule, context: _Context, candidates: Sequence[Quantity]
) -> tuple[FindingKind, ReviewReason | None, tuple[Quantity, ...]]:
    """Combine the verdicts on each candidate into one."""
    if rule.cumulative:
        caps = [
            q
            for q in candidates
            if context.before(q, _CAP_PHRASES) or context.after(q, _CAP_AFTER_PHRASES)
        ]
        if caps:
            # A stated total ("لا يتجاوز مجموعها 180 يوماً") is what the law limits.
            candidates = caps
        elif len(candidates) > 1 or context.has(_EXTENSION_PHRASES):
            return _judge_total(rule, context, candidates)
    verdicts = [_verdict(rule, q.value, q.unit) for q in candidates]
    if len({kind for kind, _ in verdicts}) == 1:
        kind, reason = verdicts[0]
        return kind, reason, tuple(candidates)
    return FindingKind.REVIEW_NEEDED, ReviewReason.CONFLICTING_VALUES, tuple(candidates)


def _judge_total(
    rule: Rule, context: _Context, candidates: Sequence[Quantity]
) -> tuple[FindingKind, ReviewReason | None, tuple[Quantity, ...]]:
    """A period plus its extensions, against a limit on the total.

    Summing is only safe when no stated figure could itself be the cap, which
    `_judge` has already ruled out. Any single period over the limit is a
    violation whatever the rest says.
    """
    over = [q for q in candidates if _verdict(rule, q.value, q.unit)[0] is FindingKind.VIOLATION]
    if over:
        return FindingKind.VIOLATION, None, tuple(over)
    periods = list(candidates)
    if len(periods) == 1 and context.has(_SAME_LENGTH_PHRASES):
        # "قابلة للتمديد لمدة مماثلة": the extension equals the first period.
        periods.append(periods[0])
    elif len(periods) == 1:
        return FindingKind.REVIEW_NEEDED, ReviewReason.OPEN_TOTAL, tuple(candidates)
    highs = [_range(rule, q.value, q.unit)[1] for q in periods]
    lows = [_range(rule, q.value, q.unit)[0] for q in periods]
    if sum(highs) <= rule.limit.value:
        return FindingKind.COMPLIANT, None, tuple(candidates)
    if sum(lows) > rule.limit.value:
        return FindingKind.VIOLATION, None, tuple(candidates)
    return FindingKind.REVIEW_NEEDED, ReviewReason.OPEN_TOTAL, tuple(candidates)


def _range(rule: Rule, value: float, unit: Unit) -> tuple[float, float]:
    bounds = convert(value, unit, rule.limit.unit)
    if bounds is None:  # pragma: no cover - Rule.__post_init__ guarantees convertibility
        raise InvalidDomainObjectError(f"{unit} does not convert to {rule.limit.unit}")
    return bounds


def _verdict(rule: Rule, value: float, unit: Unit) -> tuple[FindingKind, ReviewReason | None]:
    """Decide one stated quantity, only when its whole range is on one side."""
    low, high = _range(rule, value, unit)
    limit = rule.limit.value
    if rule.comparator is Comparator.MAXIMUM:
        return _verdict_under_ceiling(rule, low, high)
    if low >= limit:
        return FindingKind.COMPLIANT, None
    if high < limit:
        return FindingKind.VIOLATION, None
    return FindingKind.REVIEW_NEEDED, ReviewReason.INEXACT_CONVERSION


def _verdict_under_ceiling(
    rule: Rule, low: float, high: float
) -> tuple[FindingKind, ReviewReason | None]:
    limit = rule.limit.value
    if high <= limit:
        return FindingKind.COMPLIANT, None
    if low > limit + rule.exception_margin:
        return FindingKind.VIOLATION, None
    if low > limit:
        return FindingKind.REVIEW_NEEDED, ReviewReason.POSSIBLE_EXCEPTION
    return FindingKind.REVIEW_NEEDED, ReviewReason.INEXACT_CONVERSION


def _guard_violation(
    rule: Rule,
    context: _Context,
    groups: Sequence[Sequence[tuple[int, int]]],
    judged: Sequence[Quantity],
) -> tuple[FindingKind, ReviewReason | None]:
    """Downgrade a violation the clause does not fully establish."""
    if not all(context.has(group) for group in rule.requires_for_violation):
        return FindingKind.REVIEW_NEEDED, ReviewReason.CONDITION_NOT_STATED
    if rule.blocks_violation and context.has(rule.blocks_violation):
        return FindingKind.REVIEW_NEEDED, ReviewReason.POSSIBLE_EXCEPTION
    # An anchored rule has already tied its one quantity to the anchor's phrase,
    # and a rate rule's quantity carries its own rate word ("٥٤ ساعة أسبوعياً").
    # Otherwise one judged quantity must read as the amount: they all agree on
    # the violation (or add up to it), so one stated amount establishes it.
    cues = [span for group in groups for span in group]
    tied = bool(rule.anchor or rule.per)
    ceiling = rule.comparator is Comparator.MAXIMUM
    if not tied and not any(context.states(q, cues, ceiling=ceiling) for q in judged):
        return FindingKind.REVIEW_NEEDED, ReviewReason.UNCLEAR_ROLE
    return FindingKind.VIOLATION, None


def _overlaps(quantity: Quantity, span: tuple[int, int]) -> bool:
    return quantity.start < span[1] and span[0] < quantity.end


def _distance(quantity: Quantity, spans: Sequence[tuple[int, int]]) -> int:
    """Characters between ``quantity`` and the nearest span (0 if they touch)."""
    return min(max(start - quantity.end, quantity.start - end, 0) for start, end in spans)


# ---------------------------------------------------------------------- messages

_UNIT_FORMS = {
    # singular, dual, plural (3-10), accusative singular (11-99)
    Unit.HOUR: ("ساعة", "ساعتان", "ساعات", "ساعة"),
    Unit.DAY: ("يوم", "يومان", "أيام", "يوماً"),
    Unit.WEEK: ("أسبوع", "أسبوعان", "أسابيع", "أسبوعاً"),
    Unit.MONTH: ("شهر", "شهران", "أشهر", "شهراً"),
    Unit.YEAR: ("سنة", "سنتان", "سنوات", "سنة"),
}
_DUAL = 2  # Arabic has a separate form for exactly two
_PLURAL_RANGE = range(3, 11)
_ACCUSATIVE_RANGE = range(11, 100)


def format_quantity(value: float, unit: Unit) -> str:
    """Arabic rendering with digits and the grammatical form of the unit.

    Example:
        >>> [format_quantity(n, Unit.DAY) for n in (180, 3, 2)]
        ['180 يوماً', '3 أيام', 'يومان']
    """
    number = f"{value:g}"
    if unit is Unit.PERCENT:
        return f"{number}%"
    singular, dual, plural, accusative = _UNIT_FORMS[unit]
    if value != int(value):
        return f"{number} {singular}"
    whole = int(value)
    if whole == _DUAL:
        return dual
    if whole % 100 in _PLURAL_RANGE:
        return f"{number} {plural}"
    if whole % 100 in _ACCUSATIVE_RANGE:
        return f"{number} {accusative}"
    return f"{number} {singular}"


def _message(
    rule: Rule,
    kind: FindingKind,
    stated: Sequence[Quantity],
    reason: ReviewReason | None,
) -> str:
    values = "، ".join(format_quantity(q.value, q.unit) for q in stated)
    bound = "الحد الأعلى" if rule.comparator is Comparator.MAXIMUM else "الحد الأدنى"
    limit = format_quantity(rule.limit.value, rule.limit.unit)
    base = f"{rule.topic} في البند {values}، و{bound} في {rule.citation} {limit}"
    if kind is FindingKind.VIOLATION:
        return f"{base}: البند يخالف النظام."
    if kind is FindingKind.COMPLIANT:
        return f"{base}: البند متوافق مع النظام."
    detail = _REASON_TEXT[reason] if reason is not None else ""
    return f"{base}: يحتاج إلى مراجعة، {detail}."
