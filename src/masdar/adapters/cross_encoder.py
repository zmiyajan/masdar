"""Cross-encoder reranking of retrieved candidates (implements `Reranker`).

A bi-encoder embeds the question and the chunk separately; a cross-encoder
reads them together and can weigh every question word against every chunk
word (Nogueira & Cho, 2019). That is far more accurate and far slower, so it
only re-scores the short list the first stage returns.

Each candidate is shown to the model as its location in the law (law, part,
chapter, heading) on one line, then its text: the headings tell the model what
the article is about, which measured better than the text alone (ADR-0007).
"""

import threading
from collections.abc import Sequence

from masdar.adapters.torch_device import select_device
from masdar.domain.chunking import context_line
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Chunk, Hit
from masdar.ports.pair_scorer import PairScorer

DEFAULT_RERANKER_MODEL = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
"""Default cross-encoder: multilingual MiniLM fine-tuned on mMARCO.

Chosen because it fits the CPU latency budget of the public demo; the much
larger ``BAAI/bge-reranker-v2-m3`` is the quality option on a GPU (ADR-0007).
"""

DEFAULT_RERANKER_REVISION = "1427fd652930e4ba29e8149678df786c240d8825"
"""Pinned Hub commit of the default reranker: the one ADR-0007 measured."""

DEFAULT_RERANK_CANDIDATES = 30
"""First-stage hits to rerank; pass as ``SearchService(candidates=...)``.

Latency grows linearly with this number. 20 candidates lost 0.05 nDCG@10 on the
gold set; 30 keeps the 2-thread CPU median near 0.6 s with the default model.
"""

DEFAULT_ANSWER_THRESHOLD = -0.75
"""Minimum answer score for `AnswerService` with the default model and revision.

The answer score is a sum of two raw logits of this cross-encoder, so the value
means nothing for another model or revision. It is the midpoint of the two
thresholds chosen by 2-fold cross-validation on the gold and out-of-scope
questions (-1.13 and -0.37); see ADR-0009.
"""

MAX_PAIR_TOKENS = 256
"""Truncation length in tokens for one (question, chunk) pair.

A batch is padded to its longest pair, so a few long articles set the cost of
all 30. Cutting at 256 tokens kept nDCG@10 (0.888 vs 0.879 at 512) and cut the
2-thread CPU median from about 1.6 s to 0.57 s (ADR-0007).
"""


class SentenceTransformerPairScorer:
    """`PairScorer` backed by a sentence-transformers `CrossEncoder`."""

    def __init__(
        self,
        model_name: str,
        revision: str | None = None,
        device: str | None = None,
        max_length: int = MAX_PAIR_TOKENS,
    ) -> None:
        """Load the model (downloads it from Hugging Face on first use).

        Args:
            model_name: Hugging Face model id.
            revision: Hub commit to load; the latest when ``None``.
            device: ``"mps"``, ``"cuda"`` or ``"cpu"``; picked automatically if ``None``.
            max_length: Truncation length in tokens for one pair.
        """
        # Imported here, not at module level: torch is an optional extra (`ml`).
        import sentence_transformers  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415

        self._model = sentence_transformers.CrossEncoder(
            model_name, revision=revision, device=device or select_device(), max_length=max_length
        )
        # Shared by every request thread; fast tokenizers are not thread-safe.
        self._lock = threading.Lock()

    def score(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        """Score every pair in one batch, returning raw logits."""
        # One batch: the candidate list is short, and one forward pass is fastest.
        with self._lock:
            scores = self._model.predict(list(pairs), batch_size=max(1, len(pairs)))
        return [float(value) for value in scores]


class CrossEncoderReranker:
    """Reorder candidate hits by cross-encoder relevance."""

    def __init__(self, scorer: PairScorer, name: str = "rerank") -> None:
        """Create the reranker.

        Args:
            scorer: Scores (question, passage) pairs.
            name: Identifier used in hits and pipeline names.
        """
        self._scorer = scorer
        self._name = name

    @classmethod
    def from_model(
        cls,
        model_name: str = DEFAULT_RERANKER_MODEL,
        revision: str | None = DEFAULT_RERANKER_REVISION,
        device: str | None = None,
    ) -> "CrossEncoderReranker":
        """Build a reranker backed by a real cross-encoder model.

        Args:
            model_name: Hugging Face id of a cross-encoder.
            revision: Hub commit to load; pinned to the measured one by default.
            device: Torch device; picked automatically if ``None``.
        """
        return cls(SentenceTransformerPairScorer(model_name, revision=revision, device=device))

    @property
    def name(self) -> str:
        """Identifier, ``"rerank"`` by default."""
        return self._name

    @property
    def scorer(self) -> PairScorer:
        """The pair scorer, shared with the answer layer so the model loads once."""
        return self._scorer

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:
        """Return the best ``k`` of ``hits`` for ``query``, best first, ranks from 1.

        Equal scores keep the first stage's order, so results are reproducible.

        Raises:
            InvalidDomainObjectError: If the scorer returns the wrong number of scores.
        """
        if not hits or k < 1:
            return []
        question = query.strip()
        scores = self._scorer.score([(question, passage(hit.chunk)) for hit in hits])
        if len(scores) != len(hits):
            raise InvalidDomainObjectError(f"Scorer returned {len(scores)} scores for {len(hits)}")
        order = sorted(range(len(hits)), key=lambda i: (-scores[i], hits[i].rank))
        return [
            Hit(hits[index].chunk, scores[index], rank, self._name)
            for rank, index in enumerate(order[:k], start=1)
        ]


def passage(chunk: Chunk) -> str:
    """The text a cross-encoder reads for ``chunk``: its location, then its words."""
    return f"{context_line(chunk.article)}\n{chunk.text}"
