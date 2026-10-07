"""Search results at the level users cite: articles, not chunks."""

from collections.abc import Sequence
from dataclasses import dataclass

from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article, Chunk, Hit

MAX_QUERY_CHARS = 500


@dataclass(frozen=True, slots=True)
class ArticleResult:
    """One article in a result list.

    Attributes:
        article: The article.
        score: Score of its best chunk (only comparable within one list).
        rank: 1-based position in the list.
        matched: The chunk that matched best, for highlighting.
        retriever: Name of the component that produced the ranking.
    """

    article: Article
    score: float
    rank: int
    matched: Chunk
    retriever: str


def collapse_to_articles(hits: Sequence[Hit], k: int) -> list[ArticleResult]:
    """Keep each article's best chunk, in rank order, and return the top ``k``.

    Chunks of one long article can occupy several ranks; users cite articles,
    and the gold set judges articles, so ranks are recomputed per article.
    """
    seen: set[str] = set()
    results: list[ArticleResult] = []
    for hit in sorted(hits, key=lambda h: h.rank):
        article = hit.chunk.article
        if article.article_id in seen:
            continue
        seen.add(article.article_id)
        results.append(
            ArticleResult(article, hit.score, len(results) + 1, hit.chunk, hit.retriever)
        )
        if len(results) == k:
            break
    return results


def validate_query(query: str) -> str:
    """Return the trimmed query, rejecting empty or oversized input.

    Raises:
        InvalidDomainObjectError: If the query is blank or too long.
    """
    trimmed = query.strip()
    if not trimmed:
        raise InvalidDomainObjectError("The question is empty")
    if len(trimmed) > MAX_QUERY_CHARS:
        raise InvalidDomainObjectError(f"The question is longer than {MAX_QUERY_CHARS} characters")
    return trimmed
