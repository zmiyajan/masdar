"""Use case: hybrid retrieval, fusing several retrievers with RRF.

Lexical retrieval (BM25) is precise when the question uses the law's own
words; dense retrieval finds articles that say the same thing in other words.
Fusing their rankings keeps the strengths of both (see ADR-0007).
"""

from collections.abc import Sequence

from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.fusion import reciprocal_rank_fusion, validate_weights
from masdar.domain.models import Hit
from masdar.ports.retriever import Retriever

DEFAULT_FUSION_DEPTH = 100
"""Hits requested from each child before fusing.

Deeper than the final ``k`` on purpose: a chunk ranked 40th by BM25 and 3rd by
the dense retriever must be visible to the fusion to be rescued by it.
"""


class HybridRetriever:
    """A `Retriever` that fuses the rankings of its child retrievers.

    Depends only on the `Retriever` port, so any mix of retrievers (BM25,
    dense, or fakes in tests) can be fused.
    """

    def __init__(
        self,
        retrievers: Sequence[Retriever],
        weights: Sequence[float] | None = None,
        depth: int = DEFAULT_FUSION_DEPTH,
    ) -> None:
        """Create the hybrid retriever.

        Args:
            retrievers: The retrievers to fuse, at least one.
            weights: Optional RRF weight per retriever; equal when omitted.
            depth: Hits requested from each retriever before fusing.

        Raises:
            InvalidDomainObjectError: If there is no retriever, ``depth`` is
                not positive, or the weights do not match the retrievers or
                are negative or not finite.
        """
        if not retrievers:
            raise InvalidDomainObjectError("HybridRetriever needs at least one retriever")
        if depth < 1:
            raise InvalidDomainObjectError(f"depth must be >= 1, got {depth}")
        self._retrievers = tuple(retrievers)
        # Validated now, so a bad configuration fails at startup, not on a query.
        self._weights = validate_weights(weights, len(self._retrievers))
        self._depth = depth
        self._name = "hybrid(" + "+".join(r.name for r in self._retrievers) + ")"

    @property
    def name(self) -> str:
        """Name built from the children, e.g. ``"hybrid(bm25+dense)"``."""
        return self._name

    def search(self, query: str, k: int) -> list[Hit]:
        """Return the top ``k`` chunks by reciprocal rank fusion of every child."""
        if k < 1:
            return []
        per_child = max(self._depth, k)
        rankings = [retriever.search(query, per_child) for retriever in self._retrievers]
        fused = reciprocal_rank_fusion(rankings, weights=self._weights, retriever=self._name)
        return fused[:k]
