"""Core domain models.

The models are frozen dataclasses rather than Pydantic models on purpose: the
domain must not depend on third-party libraries (see ADR-0001). Validation of
untrusted input happens at the edges (API, loaders); these classes only guard
their own invariants.

Every field is immutable, so all models are hashable. Retrieval code relies on
that to deduplicate and fuse result lists (e.g. using a chunk as a dict key).
"""

import math
from dataclasses import dataclass

from masdar.domain.amendments import Amendment, ArticleStatus
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.ordinals import ArticleNumber

# Statuses whose text is served by default. Repealed and superseded articles stay
# in the corpus for history but are not current law.
CURRENT_STATUSES = frozenset(
    {ArticleStatus.IN_FORCE, ArticleStatus.AMENDED, ArticleStatus.REVIEW_NEEDED}
)


def _require_text(value: str, what: str) -> None:
    if not value.strip():
        raise InvalidDomainObjectError(f"{what} must not be blank")


@dataclass(frozen=True, slots=True)
class Article:
    """One article (مادة) of a law, with the text in force and its history.

    Attributes:
        law_id: Stable slug of the law, e.g. ``"labor-law"``.
        law_title: Official Arabic title, e.g. ``"نظام العمل"``.
        number: Official number, e.g. 79 or 79 bis.
        heading: Clean heading for citations, e.g. ``"المادة الأولى"``.
        text: The text in force (see ``status`` for how much to trust it).
        status: How ``text`` relates to the law in force.
        title: The article's own title, when the law gives one (``التعريفات``).
        part: The part (باب) the article belongs to, if any.
        chapter: The chapter (فصل) the article belongs to, if any.
        original_text: The originally published wording; ``None`` for articles
            added later by amendment.
        amendments: Every amendment note attached to the article.
    """

    law_id: str
    law_title: str
    number: ArticleNumber
    heading: str
    text: str
    status: ArticleStatus = ArticleStatus.IN_FORCE
    title: str | None = None
    part: str | None = None
    chapter: str | None = None
    original_text: str | None = None
    amendments: tuple[Amendment, ...] = ()

    def __post_init__(self) -> None:
        """Reject articles that could never be cited correctly."""
        _require_text(self.law_id, "Article.law_id")
        _require_text(self.law_title, "Article.law_title")
        _require_text(self.heading, "Article.heading")
        _require_text(self.text, f"Article {self.article_id} text")

    @property
    def article_id(self) -> str:
        """Stable id, e.g. ``"labor-law:79-bis"``; unique among current articles."""
        return f"{self.law_id}:{self.number.slug}"

    @property
    def citation(self) -> str:
        """Human-readable citation, e.g. ``"نظام العمل — المادة الأولى"``."""
        return f"{self.law_title} — {self.heading}"

    @property
    def is_current(self) -> bool:
        """True when the article belongs in default search results."""
        return self.status in CURRENT_STATUSES


@dataclass(frozen=True, slots=True)
class Chunk:
    """The unit that gets indexed and retrieved.

    Two versions of the text are kept side by side. ``text`` is what users see
    and what citations quote. ``normalized_text`` is the lossy, search-friendly
    form produced by the Arabic normalizer (optionally prefixed with the
    article's context); it is used only for matching, never shown.

    Attributes:
        chunk_id: Globally unique and stable, e.g. ``"labor-law:12#0"``.
        article: The article this chunk was cut from.
        text: Display text of this chunk.
        normalized_text: Normalized text used for indexing.
    """

    chunk_id: str
    article: Article
    text: str
    normalized_text: str

    def __post_init__(self) -> None:
        """Reject chunks that would be invisible to search or impossible to cite."""
        _require_text(self.chunk_id, "Chunk.chunk_id")
        _require_text(self.text, f"Chunk {self.chunk_id} text")
        _require_text(self.normalized_text, f"Chunk {self.chunk_id} normalized_text")


@dataclass(frozen=True, slots=True)
class Hit:
    """One ranked search result.

    Attributes:
        chunk: The retrieved chunk.
        score: Retriever-specific score; only comparable within one result list.
        rank: 1-based position in the result list.
        retriever: Name of the component that produced the hit, e.g. ``"bm25"``.
    """

    chunk: Chunk
    score: float
    rank: int
    retriever: str

    def __post_init__(self) -> None:
        """Ranks are 1-based, and a NaN or infinite score would corrupt any ranking."""
        if isinstance(self.rank, bool) or self.rank < 1:
            raise InvalidDomainObjectError(f"Hit.rank must be an int >= 1, got {self.rank!r}")
        if not math.isfinite(self.score):
            raise InvalidDomainObjectError(f"Hit.score must be finite, got {self.score!r}")
        _require_text(self.retriever, "Hit.retriever")
