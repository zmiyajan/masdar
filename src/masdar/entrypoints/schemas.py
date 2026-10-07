"""Public response shapes shared by the HTTP API and the MCP server.

Both surfaces present the same `ArticleResult` the same way, so a citation an
agent receives over MCP is identical to the one a person sees in the browser.
Domain objects stay frozen dataclasses (ADR-0001); this module is the edge
where they become validated, documented JSON.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from masdar.domain.amendments import Amendment, ArticleStatus
from masdar.domain.answer import Answer, AnswerStatus
from masdar.domain.compliance import ContractReport, FindingKind
from masdar.domain.models import Article
from masdar.domain.search import ArticleResult

# Labels shown to people. Only the first three can appear in search results
# (repealed and superseded articles are not indexed), but the mapping is total
# so a future history view cannot render a raw enum value.
STATUS_LABELS: Mapping[ArticleStatus, str] = {
    ArticleStatus.IN_FORCE: "ساري",
    ArticleStatus.AMENDED: "معدّل",
    ArticleStatus.REVIEW_NEEDED: "يحتاج مراجعة",
    ArticleStatus.REPEALED: "ملغى",
    ArticleStatus.SUPERSEDED: "مستبدل",
}


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class AmendmentOut(_Frozen):
    """Where an article's current wording comes from.

    Attributes:
        kind: What the amendment did (``replace``, ``add``, ``partial``, ...).
        decree: Royal decree, e.g. ``"م/44"``.
        issued: Hijri date of the decree, ``YYYY/MM/DD``.
        effective: Hijri date it took effect, when the note states one.
    """

    kind: str
    decree: str | None
    issued: str | None
    effective: str | None


class AmendmentNote(AmendmentOut):
    """An amendment with the note exactly as published (full history views).

    Attributes:
        note: The amendment note's original text.
    """

    note: str


class ArticleHit(_Frozen):
    """One cited article in a search result list."""

    rank: int = Field(description="1-based position in the list.")
    score: float = Field(description="Retriever score; comparable only within one list.")
    article_id: str = Field(examples=["labor-law:151"])
    citation: str = Field(examples=["نظام العمل — المادة الحادية والخمسون بعد المائة"])
    heading: str
    article_title: str | None
    law_id: str
    law_title: str
    part: str | None
    chapter: str | None
    text: str = Field(description="The full text in force.")
    matched_text: str = Field(description="The passage that matched best.")
    status: ArticleStatus
    status_label: str = Field(examples=["ساري"])
    latest_amendment: AmendmentOut | None
    source_url: str | None = Field(description="The law's page on the official portal.")


class SearchResponse(_Frozen):
    """A ranked list of cited articles for one question."""

    query: str
    k: int
    laws: list[str]
    pipeline: str = Field(description="Retrieval pipeline that produced the ranking.")
    results: list[ArticleHit]


class Quote(_Frozen):
    """One sentence of the law, quoted verbatim, that answers the question.

    Attributes:
        article_id: Article the sentence comes from, e.g. ``"labor-law:53"``.
        citation: Law and article number, ready to cite.
        sentence: Exact text from the article in force; never generated.
        source_url: Official page of the law.
    """

    article_id: str
    citation: str
    sentence: str
    source_url: str | None


class AnswerResponse(_Frozen):
    """A quoted answer (or a refusal) plus the articles it was read from."""

    query: str
    laws: list[str]
    status: AnswerStatus = Field(
        description="`answered` when `quotes` holds the law's own words; `not_found` otherwise."
    )
    quotes: list[Quote]
    pipeline: str = Field(description="Answer service that produced it.")
    results: list[ArticleHit] = Field(description="Related articles, best first.")


class CheckRequest(_Frozen):
    """A contract or HR policy to check."""

    text: str = Field(description="The document, as pasted (Arabic).", max_length=20_000)
    laws: list[str] | None = Field(
        default=None, description="Restrict related articles and rules to these law ids."
    )


class FindingOut(_Frozen):
    """One verdict on one clause, with the article it rests on.

    Attributes:
        rule_id: Stable rule id, e.g. ``"probation-max"``.
        article_id: The article whose text in force states the limit.
        citation: Law and article number, ready to cite.
        kind: ``violation``, ``compliant`` or ``review_needed``.
        kind_label: The verdict in Arabic.
        message: Arabic explanation: stated amount, the limit, the article.
        source_url: Official page of the law.
    """

    rule_id: str
    article_id: str
    citation: str
    kind: FindingKind
    kind_label: str
    message: str
    source_url: str | None


class ClauseOut(_Frozen):
    """One clause of the document with its verdicts and related articles."""

    index: int
    text: str
    findings: list[FindingOut]
    related: list[ArticleHit]


class CheckResponse(_Frozen):
    """Every clause in document order, plus verdict counts."""

    counts: dict[FindingKind, int]
    clauses: list[ClauseOut]


VERDICT_LABELS: Mapping[FindingKind, str] = {
    FindingKind.VIOLATION: "مخالفة",
    FindingKind.COMPLIANT: "متوافق",
    FindingKind.REVIEW_NEEDED: "يحتاج مراجعة",
}


class ArticleDetail(_Frozen):
    """One article with its full amendment history."""

    article_id: str
    citation: str
    heading: str
    article_title: str | None
    law_id: str
    law_title: str
    part: str | None
    chapter: str | None
    text: str
    original_text: str | None
    status: ArticleStatus
    status_label: str
    amendments: list[AmendmentNote]
    source_url: str | None


class ErrorBody(_Frozen):
    """A failure explained in both languages."""

    code: str = Field(examples=["invalid_query"])
    message: str
    message_ar: str


class ErrorResponse(_Frozen):
    """The envelope of every error the API returns."""

    error: ErrorBody


class HealthResponse(_Frozen):
    """Liveness and the pipeline being served."""

    status: Literal["ok"] = "ok"
    pipeline: str
    answers: bool = Field(default=False, description="Whether `/api/answer` is offered.")
    version: str


def latest_amendment(amendments: tuple[Amendment, ...]) -> Amendment | None:
    """The most recent amendment: the latest decree date, else the last published.

    Undated notes cannot be placed in time, so a dated one is preferred; among
    undated notes the portal's publication order (oldest first) decides.
    """
    # The position breaks ties between notes of the same decree date: later wins.
    dated = [(a.issued, position, a) for position, a in enumerate(amendments) if a.issued]
    if dated:
        return max(dated, key=lambda entry: (entry[0], entry[1]))[2]
    return amendments[-1] if amendments else None


def _amendment_out(amendment: Amendment) -> AmendmentOut:
    return AmendmentOut(
        kind=amendment.kind.value,
        decree=amendment.decree,
        issued=str(amendment.issued) if amendment.issued else None,
        effective=str(amendment.effective) if amendment.effective else None,
    )


def to_hit(result: ArticleResult, source_urls: Mapping[str, str]) -> ArticleHit:
    """Present one search result.

    Args:
        result: The ranked article.
        source_urls: Official page per law id.
    """
    article = result.article
    latest = latest_amendment(article.amendments)
    return ArticleHit(
        rank=result.rank,
        score=result.score,
        article_id=article.article_id,
        citation=article.citation,
        heading=article.heading,
        article_title=article.title,
        law_id=article.law_id,
        law_title=article.law_title,
        part=article.part,
        chapter=article.chapter,
        text=article.text,
        matched_text=result.matched.text,
        status=article.status,
        status_label=STATUS_LABELS[article.status],
        latest_amendment=_amendment_out(latest) if latest else None,
        source_url=source_urls.get(article.law_id),
    )


def to_detail(article: Article, source_urls: Mapping[str, str]) -> ArticleDetail:
    """Present one article with every amendment note.

    Args:
        article: The article.
        source_urls: Official page per law id.
    """
    return ArticleDetail(
        article_id=article.article_id,
        citation=article.citation,
        heading=article.heading,
        article_title=article.title,
        law_id=article.law_id,
        law_title=article.law_title,
        part=article.part,
        chapter=article.chapter,
        text=article.text,
        original_text=article.original_text,
        status=article.status,
        status_label=STATUS_LABELS[article.status],
        amendments=[
            AmendmentNote(**_amendment_out(a).model_dump(), note=a.note) for a in article.amendments
        ],
        source_url=source_urls.get(article.law_id),
    )


def to_answer(
    answer: Answer, laws: list[str], pipeline: str, source_urls: Mapping[str, str]
) -> AnswerResponse:
    """Present an extractive answer with its related articles.

    Args:
        answer: The answer or refusal.
        laws: The law filter the question was asked with.
        pipeline: Name of the answer service.
        source_urls: Official page per law id.
    """
    return AnswerResponse(
        query=answer.question,
        laws=laws,
        status=answer.status,
        quotes=[
            Quote(
                article_id=evidence.article.article_id,
                citation=evidence.article.citation,
                sentence=evidence.sentence,
                source_url=source_urls.get(evidence.article.law_id),
            )
            for evidence in answer.evidence
        ],
        pipeline=pipeline,
        results=[to_hit(result, source_urls) for result in answer.related],
    )


def to_check(report: ContractReport, source_urls: Mapping[str, str]) -> CheckResponse:
    """Present a contract check.

    Args:
        report: Clause-by-clause verdicts and related articles.
        source_urls: Official page per law id.
    """
    return CheckResponse(
        counts=dict(report.counts),
        clauses=[
            ClauseOut(
                index=clause.clause.index,
                text=clause.clause.text,
                findings=[
                    FindingOut(
                        rule_id=finding.rule.rule_id,
                        article_id=finding.rule.article_id,
                        citation=finding.rule.citation,
                        kind=finding.kind,
                        kind_label=VERDICT_LABELS[finding.kind],
                        message=finding.message,
                        source_url=source_urls.get(finding.rule.law_id),
                    )
                    for finding in clause.findings
                ],
                related=[to_hit(result, source_urls) for result in clause.related],
            )
            for clause in report.clauses
        ],
    )
