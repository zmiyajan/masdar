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
