"""Reciprocal Rank Fusion: merge ranked lists by rank, not by score.

BM25 scores are unbounded term-weight sums; cosine similarities live in
``[-1, 1]`` and bunch up near the top. Adding or normalizing such scores lets
whichever retriever has the wider spread dominate. RRF (Cormack, Clarke &
Büttcher, 2009) ignores score magnitudes and adds ``weight / (k + rank)`` for
every list a document appears in. A document ranked well by several retrievers
rises; one found by a single retriever still survives. ``k = 60`` damps the
advantage of the very first ranks and is the value from the paper, which
remains a robust default without tuning.
"""

import math
from collections.abc import Sequence

from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Chunk, Hit

RRF_K = 60
"""Rank constant from Cormack et al. (2009); larger values flatten the curve."""


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[Hit]],
    *,
    weights: Sequence[float] | None = None,
    k: int = RRF_K,
    retriever: str = "rrf",
) -> list[Hit]:
    """Fuse ranked hit lists into one list ordered by RRF score.

    Each list contributes ``weight / (k + hit.rank)`` to every chunk it holds.
    The hit's own ``rank`` is used rather than its position, so a list that was
    filtered after ranking still contributes its original ranks. If a list
    holds the same chunk twice, only its best-ranked occurrence counts.

    Ties are broken by ``chunk_id``, so the output never depends on the order
    in which the input lists are given.

    Args:
        rankings: One ranked list per retriever.
        weights: One non-negative weight per list; all ``1.0`` when omitted.
        k: The RRF rank constant; must be positive.
        retriever: Name stamped on every fused hit.

    Returns:
        Every distinct chunk, best first, with ranks from 1 and RRF scores.

    Raises:
        InvalidDomainObjectError: If ``k`` is not positive, or the weights do
            not match the lists or are negative or not finite.
    """
    if isinstance(k, bool) or k < 1:
        raise InvalidDomainObjectError(f"RRF k must be an int >= 1, got {k!r}")
    list_weights = validate_weights(weights, len(rankings))

    scores: dict[str, float] = {}
    chunks: dict[str, Chunk] = {}
    for hits, weight in zip(rankings, list_weights, strict=True):
        best_rank: dict[str, int] = {}
        for hit in hits:
            chunk_id = hit.chunk.chunk_id
            if chunk_id not in best_rank or hit.rank < best_rank[chunk_id]:
                best_rank[chunk_id] = hit.rank
            chunks.setdefault(chunk_id, hit.chunk)
        for chunk_id, rank in best_rank.items():
            scores[chunk_id] = scores.get(chunk_id, 0.0) + weight / (k + rank)

    ordered = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))
    return [
        Hit(chunks[chunk_id], scores[chunk_id], rank, retriever)
        for rank, chunk_id in enumerate(ordered, start=1)
    ]


def validate_weights(weights: Sequence[float] | None, lists: int) -> tuple[float, ...]:
    """Return one RRF weight per ranked list, defaulting to equal weights.

    Args:
        weights: The weights to check, or ``None`` for all ``1.0``.
        lists: How many ranked lists will be fused.

    Raises:
        InvalidDomainObjectError: If the count does not match ``lists`` or a
            weight is negative or not finite.
    """
    if weights is None:
        return (1.0,) * lists
    if len(weights) != lists:
        raise InvalidDomainObjectError(f"Got {len(weights)} weights for {lists} ranked lists")
    for weight in weights:
        if not math.isfinite(weight) or weight < 0:
            raise InvalidDomainObjectError(f"RRF weights must be finite and >= 0, got {weight!r}")
    return tuple(weights)
