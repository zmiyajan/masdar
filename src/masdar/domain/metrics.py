"""Ranking metrics over article ids, judged against graded relevance.

Conventions follow trec_eval / pytrec_eval as used by BEIR (Thakur et al.,
2021), so numbers are comparable with published results:

- **Relevant** means any positive grade (1 = related, 2 = answers). Recall and
  MRR are binary over that set.
- **nDCG** uses the grades themselves as gains with a ``log2(rank + 1)``
  discount (Järvelin & Kekäläinen, 2002), normalized by the ideal ordering of
  *all* judged articles, so missing a judged article costs score.

Every function takes a ranking without duplicates, best first, and a mapping
``article_id -> grade``. Unjudged articles count as not relevant.
"""

import math
from collections.abc import Mapping, Sequence

from masdar.domain.errors import InvalidDomainObjectError


def _top(ranking: Sequence[str], k: int) -> Sequence[str]:
    if k < 1:
        raise InvalidDomainObjectError(f"k must be >= 1, got {k}")
    if len(set(ranking)) != len(ranking):
        raise InvalidDomainObjectError("A ranking must not repeat an article")
    return ranking[:k]


def recall_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    """Share of the relevant articles that appear in the top ``k``.

    Example:
        >>> recall_at_k(["a", "x", "b"], {"a": 2, "b": 1, "c": 1}, k=2)
        0.3333333333333333
    """
    relevant = {article for article, grade in grades.items() if grade > 0}
    if not relevant:
        return 0.0
    return len(relevant.intersection(_top(ranking, k))) / len(relevant)


def reciprocal_rank_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    """``1 / rank`` of the first relevant article in the top ``k``, else 0.

    Averaged over queries this is MRR@k.

    Example:
        >>> reciprocal_rank_at_k(["x", "y", "b"], {"a": 2, "b": 1}, k=10)
        0.3333333333333333
    """
    for rank, article in enumerate(_top(ranking, k), start=1):
        if grades.get(article, 0) > 0:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(ranking: Sequence[str], grades: Mapping[str, int], k: int) -> float:
    """Normalized discounted cumulative gain at ``k``, with graded gains.

    ``DCG@k = sum(grade_i / log2(i + 1))`` for ranks ``i = 1..k``, divided by the
    DCG of the best possible ordering of the judged articles.

    Example:
        >>> round(ndcg_at_k(["a", "x", "c"], {"a": 2, "c": 1}, k=10), 4)
        0.9502
    """
    gains = [grades.get(article, 0) for article in _top(ranking, k)]
    ideal = sorted((grade for grade in grades.values() if grade > 0), reverse=True)[:k]
    best = _dcg(ideal)
    return _dcg(gains) / best if best > 0 else 0.0


def first_rank(ranking: Sequence[str], grades: Mapping[str, int], grade: int) -> int | None:
    """1-based rank of the first article judged at least ``grade``, or ``None``.

    Example:
        >>> first_rank(["x", "b", "a"], {"a": 2, "b": 1}, grade=2)
        3
    """
    for rank, article in enumerate(ranking, start=1):
        if grades.get(article, 0) >= grade:
            return rank
    return None


def _dcg(gains: Sequence[int]) -> float:
    return sum(gain / math.log2(rank + 1) for rank, gain in enumerate(gains, start=1))
