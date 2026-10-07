"""Port: score how well a passage answers a question (e.g. a cross-encoder)."""

from collections.abc import Sequence
from typing import Protocol


class PairScorer(Protocol):
    """Scores (question, passage) pairs; the seam that keeps tests model-free.

    Reranking scores whole chunks with it, and the answer layer scores single
    sentences with the same model, so one loaded model serves both.
    """

    def score(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        """Return one relevance score per pair, higher is better."""
        ...
