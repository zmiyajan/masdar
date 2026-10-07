"""Use case: answer a question with ranked, citable articles."""

from collections.abc import Collection

from masdar.domain.models import Hit
from masdar.domain.search import ArticleResult, collapse_to_articles, validate_query
from masdar.ports.reranker import Reranker
from masdar.ports.retriever import Retriever


class SearchService:
    """Retrieve candidates, optionally rerank them, and return articles.

    The API, the CLI, the MCP server and the evaluation all go through this
    one class, so what is measured is exactly what users get.
    """

    def __init__(
        self, retriever: Retriever, reranker: Reranker | None = None, candidates: int = 50
    ) -> None:
        """Create the service.

        Args:
            retriever: First-stage retriever.
            reranker: Optional second stage applied to the candidates.
            candidates: How many chunks the first stage hands to the second.
        """
        self._retriever = retriever
        self._reranker = reranker
        self._candidates = candidates

    @property
    def retriever(self) -> Retriever:
        """The first stage."""
        return self._retriever

    @property
    def reranker(self) -> Reranker | None:
        """The second stage, if any; the answer layer reuses its model."""
        return self._reranker

    @property
    def name(self) -> str:
        """Pipeline name, e.g. ``"hybrid+rerank"``."""
        if self._reranker is None:
            return self._retriever.name
        return f"{self._retriever.name}+{self._reranker.name}"

    def search(
        self, query: str, k: int = 10, laws: Collection[str] | None = None
    ) -> list[ArticleResult]:
        """Return up to ``k`` articles for ``query``, optionally within ``laws``.

        Raises:
            InvalidDomainObjectError: If the query is empty or too long.
        """
        question = validate_query(query)
        hits = (
            self._candidates_within(question, laws)
            if laws
            else self._retriever.search(question, self._candidates)
        )
        if self._reranker is not None:
            hits = self._reranker.rerank(question, hits, self._candidates)
        return collapse_to_articles(hits, k)

    def _candidates_within(self, question: str, laws: Collection[str]) -> list[Hit]:
        """The best ``candidates`` hits from ``laws`` only.

        Filtering a fixed top-N would starve small laws: their articles may all
        rank below another law's. So the retriever is asked for more until
        enough hits pass the filter or it has nothing left to give.
        """
        depth = self._candidates
        while True:
            hits = self._retriever.search(question, depth)
            kept = [hit for hit in hits if hit.chunk.article.law_id in laws]
            if len(kept) >= self._candidates or len(hits) < depth:
                return kept[: self._candidates]
            depth *= 2
