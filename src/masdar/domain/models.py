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

from masdar.domain.errors import InvalidDomainObjectError


def _require_text(value: str, what: str) -> None:
    if not value.strip():
        raise InvalidDomainObjectError(f"{what} must not be blank")


@dataclass(frozen=True, slots=True)
class Article:
    """One article (مادة) of a law, as published.

    Attributes:
        law_id: Stable slug of the law, e.g. ``"labor-law"``.
        law_title: Official Arabic title, e.g. ``"نظام العمل"``.
        number: 1-based position of the article within the law.
        heading: The article heading as published, e.g. ``"المادة الأولى"``.
        text: Original article text, kept verbatim for display and citation.
        part: The part (باب) the article belongs to, if any.
        chapter: The chapter (فصل) the article belongs to, if any.
    """

    law_id: str
    law_title: str
    number: int
    heading: str
    text: str
    part: str | None = None
    chapter: str | None = None

    def __post_init__(self) -> None:
        """Reject articles that could never be cited correctly."""
        _require_text(self.law_id, "Article.law_id")
        _require_text(self.law_title, "Article.law_title")
        _require_text(self.heading, "Article.heading")
        # bool is a subclass of int; True must not silently become article 1.
        if isinstance(self.number, bool) or self.number < 1:
            raise InvalidDomainObjectError(
                f"Article.number must be an int >= 1, got {self.number!r}"
            )
        _require_text(self.text, f"Article {self.law_id}#{self.number} text")

    @property
    def citation(self) -> str:
        """Human-readable citation, e.g. ``"نظام العمل — المادة الأولى"``."""
        return f"{self.law_title} — {self.heading}"


@dataclass(frozen=True, slots=True)
class Chunk:
    """The unit that gets indexed and retrieved.

    Two versions of the text are kept side by side. ``text`` is the original and
    is what users see and what citations quote. ``normalized_text`` is the
    lossy, search-friendly form produced by the Arabic normalizer; it is used
    only for matching, never shown.

    Attributes:
        chunk_id: Globally unique and stable, e.g. ``"labor-law:12:0"``.
        article: The article this chunk was cut from.
        text: Original text of this chunk.
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
