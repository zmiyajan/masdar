"""Extractive answers: the law's own sentences, quoted verbatim, or an honest refusal.

An answer here is never written; it is *selected*. The answer layer splits the
retrieved articles into sentences, scores each sentence against the question
and returns the best ones exactly as they appear in the article, with the
article for citation. If no sentence scores high enough, the answer is
"not found". Because every quoted sentence is a substring of the article it
cites, the answer cannot say anything the law does not say (ADR-0009).
"""

import math
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.gold import ANSWERS, RELATED, GoldQuery, QueryStyle
from masdar.domain.models import Article
from masdar.domain.search import ArticleResult

MIN_UNIT_WORDS = 4
"""Units shorter than this are merged into a neighbour.

A bare paragraph marker ("أ-"), a heading-like "وفق ما يلي:" or "ما يأتي:" is
not an answer on its own, and a cross-encoder scores such fragments erratically.
"""

# A unit ends at a line break, or after a full stop / Arabic semicolon / Latin
# semicolon that is followed by whitespace. Requiring the whitespace keeps
# decimals ("1.5") and abbreviations without spaces intact. A colon is not a
# boundary inside a line ("ومن ذلك: الاسم ..."), and a colon that introduces a
# list already ends its line, so the line break splits it.
_BOUNDARY = re.compile(r"\n+|(?<=[.؛;])[^\S\n]+")

_WORD = re.compile(r"\S+")


def split_sentences(text: str) -> list[str]:
    r"""Split an article's display text into answerable units, verbatim.

    Boundaries are line breaks (each numbered paragraph such as ``1-`` or
    ``أ-`` sits on its own line in the source) and sentence-ending ``.``,
    ``؛`` or ``;``. Units under `MIN_UNIT_WORDS` words are merged with the next
    unit (or the previous one, at the end) so markers and lead-ins never stand
    alone.

    Merging extends a span over the original text instead of joining strings,
    so every unit is an exact substring of ``text``, only stripped of
    surrounding whitespace.

    Args:
        text: An article's display text.

    Returns:
        The units in reading order; empty if ``text`` is blank.

    Examples:
        >>> split_sentences("1- للعامل إجازة سنوية. ولا يجوز التنازل عنها.\n2- قصير")
        ['1- للعامل إجازة سنوية.', 'ولا يجوز التنازل عنها.\n2- قصير']
    """
    spans = list(_spans(text))
    merged: list[tuple[int, int]] = []
    pending: tuple[int, int] | None = None
    for span_start, end in spans:
        # A pending short unit is glued to the front of this one.
        start = pending[0] if pending is not None else span_start
        pending = None
        if _words(text[start:end]) < MIN_UNIT_WORDS:
            pending = (start, end)
            continue
        merged.append((start, end))
    if pending is not None:
        if merged:
            merged[-1] = (merged[-1][0], pending[1])
        else:
            merged.append(pending)
    return [text[start:end].strip() for start, end in merged]


def _spans(text: str) -> Iterator[tuple[int, int]]:
    """``(start, end)`` of every non-blank piece between boundaries."""
    start = 0
    for boundary in _BOUNDARY.finditer(text):
        if text[start : boundary.start()].strip():
            yield start, boundary.start()
        start = boundary.end()
    if text[start:].strip():
        yield start, len(text)


def _words(text: str) -> int:
    return len(_WORD.findall(text))


class AnswerStatus(StrEnum):
    """Whether the law answers the question, as far as Masdar can tell."""

    ANSWERED = "answered"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class Evidence:
    """One sentence of the law, quoted verbatim, that answers the question.

    Attributes:
        article: The article the sentence is quoted from (the citation).
        sentence: The sentence, an exact substring of ``article.text``.
        score: Answer score (only comparable within one model and rule).
    """

    article: Article
    sentence: str
    score: float

    def __post_init__(self) -> None:
        """A quote that is not in the article would be a fabricated citation."""
        if not self.sentence.strip() or self.sentence not in self.article.text:
            raise InvalidDomainObjectError(
                f"Evidence sentence is not a verbatim part of {self.article.article_id}"
            )
        if not math.isfinite(self.score):
            raise InvalidDomainObjectError(f"Evidence.score must be finite, got {self.score!r}")


@dataclass(frozen=True, slots=True)
class Answer:
    """The answer to one question.

    Attributes:
        question: The question as asked.
        status: ``ANSWERED`` when ``evidence`` holds at least one sentence.
        evidence: Quoted sentences, best first.
        related: The retrieved articles, for reading around the answer (also
            returned with ``NOT_FOUND``, so the user still has a starting point).
    """

    question: str
    status: AnswerStatus
    evidence: tuple[Evidence, ...]
    related: tuple[ArticleResult, ...] = ()

    def __post_init__(self) -> None:
        """An answer without evidence, or a refusal with evidence, is contradictory."""
        if (self.status is AnswerStatus.ANSWERED) != bool(self.evidence):
            raise InvalidDomainObjectError(
                f"Answer status {self.status} does not match {len(self.evidence)} evidence"
            )

    @property
    def top(self) -> Evidence | None:
        """The best evidence, or ``None`` when not found."""
        return self.evidence[0] if self.evidence else None


@dataclass(frozen=True, slots=True)
class OutOfScopeQuestion:
    """A question the corpus does not answer; the right response is a refusal.

    Attributes:
        query_id: Stable id, e.g. ``"oos-001"``.
        text: The question as a user would type it.
        topic: What it is really about, e.g. ``"traffic"`` or ``"near-miss"``.
        style: How it is worded.
    """

    query_id: str
    text: str
    topic: str
    style: QueryStyle

    def __post_init__(self) -> None:
        """A blank question cannot be asked."""
        if not self.query_id.strip() or not self.text.strip():
            raise InvalidDomainObjectError("OutOfScopeQuestion needs an id and a text")


# ------------------------------------------------------------------------- quality


@dataclass(frozen=True, slots=True)
class AnswerQualityReport:
    """How well an answer service attributes and abstains.

    Rates over the gold set use every gold question as the denominator: a
    refusal counts as a miss, because that is what the user experiences.

    Attributes:
        service: Name of the answer service measured.
        gold_questions: Number of gold questions (answerable).
        out_of_scope_questions: Number of out-of-scope questions.
        attributed: Gold questions whose top evidence comes from a grade-2 article.
        relevant: Gold questions whose top evidence comes from a grade >= 1 article.
        false_refusals: Gold questions answered with ``NOT_FOUND``.
        correct_refusals: Out-of-scope questions answered with ``NOT_FOUND``.
    """

    service: str
    gold_questions: int
    out_of_scope_questions: int
    attributed: int
    relevant: int
    false_refusals: int
    correct_refusals: int

    @property
    def attribution_accuracy(self) -> float:
        """Share of gold questions whose top evidence is from an answering article."""
        return _rate(self.attributed, self.gold_questions)

    @property
    def any_relevant_accuracy(self) -> float:
        """Share of gold questions whose top evidence is from a relevant article."""
        return _rate(self.relevant, self.gold_questions)

    @property
    def false_refusal_rate(self) -> float:
        """Share of gold questions refused although the law answers them."""
        return _rate(self.false_refusals, self.gold_questions)

    @property
    def wrong_answer_rate(self) -> float:
        """Among answered gold questions, the share quoting an irrelevant article.

        This is the harm metric: a confident quote from the wrong article.
        """
        answered = self.gold_questions - self.false_refusals
        return _rate(answered - self.relevant, answered)

    @property
    def correct_refusal_rate(self) -> float:
        """Share of out-of-scope questions that were refused."""
        return _rate(self.correct_refusals, self.out_of_scope_questions)

    def to_dict(self) -> dict[str, str | int | float]:
        """JSON-ready form: counts, then rates rounded to 4 decimals."""
        return {
            "service": self.service,
            "gold_questions": self.gold_questions,
            "out_of_scope_questions": self.out_of_scope_questions,
            "attributed": self.attributed,
            "relevant": self.relevant,
            "false_refusals": self.false_refusals,
            "correct_refusals": self.correct_refusals,
            "attribution_accuracy": round(self.attribution_accuracy, 4),
            "any_relevant_accuracy": round(self.any_relevant_accuracy, 4),
            "false_refusal_rate": round(self.false_refusal_rate, 4),
            "wrong_answer_rate": round(self.wrong_answer_rate, 4),
            "correct_refusal_rate": round(self.correct_refusal_rate, 4),
        }


def _rate(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def top_evidence_grade(query: GoldQuery, answer: Answer) -> int:
    """Gold grade of the article the top evidence quotes; 0 if refused or unjudged."""
    top = answer.top
    if top is None:
        return 0
    grades: Mapping[str, int] = query.grades
    return grades.get(top.article.article_id, 0)


def summarize_answers(
    service: str,
    gold: Sequence[tuple[GoldQuery, Answer]],
    out_of_scope: Sequence[Answer],
) -> AnswerQualityReport:
    """Score answers to gold and out-of-scope questions.

    Args:
        service: Name of the answer service measured.
        gold: Each gold question with the answer it received.
        out_of_scope: Answers to questions the corpus does not answer.

    Raises:
        InvalidDomainObjectError: If there are no gold questions.
    """
    if not gold:
        raise InvalidDomainObjectError("Cannot summarize answers without gold questions")
    grades = [top_evidence_grade(query, answer) for query, answer in gold]
    return AnswerQualityReport(
        service=service,
        gold_questions=len(gold),
        out_of_scope_questions=len(out_of_scope),
        attributed=sum(grade == ANSWERS for grade in grades),
        relevant=sum(grade >= RELATED for grade in grades),
        false_refusals=sum(answer.status is AnswerStatus.NOT_FOUND for _, answer in gold),
        correct_refusals=sum(answer.status is AnswerStatus.NOT_FOUND for answer in out_of_scope),
    )
