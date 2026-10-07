"""BM25 lexical retrieval over chunks (implements `Retriever`).

BM25 (Robertson & Zaragoza, 2009) is the baseline every retrieval system must
beat: on BEIR (Thakur et al., 2021) it is still competitive with dense models
out of domain. The scoring itself comes from ``rank_bm25.BM25Okapi`` with its
default parameters (k1 = 1.5, b = 0.75); this adapter decides what is indexed
and how text becomes tokens, which is where Arabic retrieval wins or loses.
"""

from collections.abc import Callable, Sequence

from rank_bm25 import BM25Okapi

from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Chunk, Hit
from masdar.domain.tokenize import ArabicTokenizer

Analyzer = Callable[[str], Sequence[str]]
"""Turns a text (document or query) into the tokens BM25 compares."""


def arabic_analyzer(
    normalizer: ArabicNormalizer | None = None, tokenizer: ArabicTokenizer | None = None
) -> Analyzer:
    """Normalize, then tokenize: the analysis applied to documents *and* queries.

    Re-normalizing ``Chunk.normalized_text`` is a no-op (normalization is
    idempotent), so one analyzer serves both sides and they can never drift.

    Args:
        normalizer: Defaults to `ArabicNormalizer()`.
        tokenizer: Defaults to `ArabicTokenizer()`.
    """
    norm = normalizer or ArabicNormalizer()
    tok = tokenizer or ArabicTokenizer()

    def analyze(text: str) -> list[str]:
        return tok.tokenize(norm.normalize(text))

    return analyze


def whitespace_analyzer(text: str) -> list[str]:
    """Split on whitespace only: the no-normalization baseline of the ablation."""
    return text.split()


def search_text(chunk: Chunk) -> str:
    """The text a chunk is indexed by: normalized, possibly with its context prefix."""
    return chunk.normalized_text


def display_text(chunk: Chunk) -> str:
    """The chunk's original words, used only by the raw baseline."""
    return chunk.text


class Bm25Retriever:
    """Okapi BM25 over a fixed set of chunks, built once in memory.

    About 540 chunks index in milliseconds, so there is no persisted index to
    keep in sync with the corpus.
    """

    def __init__(
        self,
        chunks: Sequence[Chunk],
        *,
        name: str = "bm25",
        analyzer: Analyzer | None = None,
        text_of: Callable[[Chunk], str] = search_text,
    ) -> None:
        """Index ``chunks``.

        Args:
            chunks: What to search; their order does not affect the ranking.
            name: Pipeline name reported in hits and evaluation results.
            analyzer: Applied to every document and every query. Defaults to
                `arabic_analyzer()`.
            text_of: Which text of a chunk to index. Defaults to `search_text`.

        Raises:
            InvalidDomainObjectError: If ``chunks`` is empty (BM25 needs an
                average document length).
        """
        if not chunks:
            raise InvalidDomainObjectError("Bm25Retriever needs at least one chunk")
        self._name = name
        self._analyze = analyzer or arabic_analyzer()
        self._chunks = tuple(chunks)
        self._index = BM25Okapi([list(self._analyze(text_of(chunk))) for chunk in self._chunks])

    @property
    def name(self) -> str:
        """Pipeline name, e.g. ``"bm25"``."""
        return self._name

    def search(self, query: str, k: int) -> list[Hit]:
        """Return up to ``k`` chunks that share at least one term with ``query``.

        Chunks scoring zero or less match nothing useful and are dropped, so a
        query of stopwords returns no hits rather than arbitrary ones. Equal
        scores are ordered by ``chunk_id`` so results never depend on the
        corpus order or on sort stability.
        """
        tokens = list(self._analyze(query))
        if k < 1 or not tokens:
            return []
        scores = [float(score) for score in self._index.get_scores(tokens)]
        ranked = sorted(
            (pair for pair in zip(scores, self._chunks, strict=True) if pair[0] > 0),
            key=lambda pair: (-pair[0], pair[1].chunk_id),
        )
        return [
            Hit(chunk=chunk, score=score, rank=rank, retriever=self._name)
            for rank, (score, chunk) in enumerate(ranked[:k], start=1)
        ]
