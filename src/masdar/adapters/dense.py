"""Dense (semantic) retrieval with a multilingual E5 bi-encoder (implements `Retriever`).

Questions and chunks are embedded into one vector space, and chunks are ranked
by cosine similarity to the question (Karpukhin et al., 2020). This finds
articles that use different words from the question: "إجازة الأمومة" matches
an article that only says "إجازة وضع".

The default model is ``intfloat/multilingual-e5-small`` (Wang et al., 2024).
E5 was trained with the prefixes ``"query: "`` and ``"passage: "``, and drops
in quality without them, so both are applied here.

The display ``text`` is embedded, not ``normalized_text``: letter folding
(``ة`` -> ``ه``) produces spellings the model rarely saw in training, and the
gold set measured it clearly worse (ADR-0007). For the same reason the query
is not normalized either.

Corpus embeddings are cached in a ``.npy`` file whose name carries a SHA-256
fingerprint of the exact strings embedded, so any corpus change invalidates the
cache by construction.
"""

import hashlib
import logging
import os
import re
import tempfile
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from masdar.adapters.torch_device import select_device
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Chunk, Hit

DEFAULT_EMBEDDING_MODEL = "intfloat/multilingual-e5-small"
"""Default bi-encoder: 118M parameters, measured on par with mE5-base here (ADR-0007)."""

DEFAULT_EMBEDDING_REVISION = "614241f622f53c4eeff9890bdc4f31cfecc418b3"
"""Pinned Hub commit of the default model: the one ADR-0007 measured. An upstream
update can then never change results silently, and it is part of the cache key."""

_log = logging.getLogger(__name__)

DEFAULT_CACHE_DIR = Path("data/index")
"""Where corpus embeddings are cached; gitignored and safe to delete."""

QUERY_PREFIX = "query: "
"""E5 instruction prefix for questions."""

PASSAGE_PREFIX = "passage: "
"""E5 instruction prefix for indexed chunks."""

Embeddings = npt.NDArray[np.float32]
"""A ``(rows, dimensions)`` matrix, one embedding per row."""


class Encoder(Protocol):
    """Turns texts into embedding vectors; the seam that keeps tests model-free."""

    def encode(self, texts: Sequence[str]) -> Embeddings:
        """Return one row per text, in input order."""
        ...


class SentenceTransformerEncoder:
    """`Encoder` backed by a sentence-transformers model."""

    def __init__(
        self,
        model_name: str,
        revision: str | None = None,
        device: str | None = None,
        batch_size: int = 32,
    ) -> None:
        """Load the model (downloads it from Hugging Face on first use).

        Args:
            model_name: Hugging Face model id.
            revision: Hub commit to load; the latest when ``None``.
            device: ``"mps"``, ``"cuda"`` or ``"cpu"``; picked automatically if ``None``.
            batch_size: Texts per forward pass when encoding.
        """
        # Imported here, not at module level: torch is an optional extra (`ml`),
        # and everything else in this module must stay importable without it.
        import sentence_transformers  # type: ignore[import-not-found,unused-ignore]  # noqa: PLC0415

        self._model = sentence_transformers.SentenceTransformer(
            model_name, revision=revision, device=device or select_device()
        )
        self._batch_size = batch_size
        # One model is shared by every request thread of the web app, and fast
        # tokenizers are not safe to call concurrently ("Already borrowed").
        self._lock = threading.Lock()

    def encode(self, texts: Sequence[str]) -> Embeddings:
        """Embed ``texts`` as unit-length float32 rows."""
        with self._lock:
            vectors = self._model.encode(
                list(texts), batch_size=self._batch_size, normalize_embeddings=True
            )
        return np.asarray(vectors, dtype=np.float32)


class DenseRetriever:
    """Rank chunks by cosine similarity between E5 embeddings."""

    def __init__(
        self,
        chunks: Sequence[Chunk],
        encoder: Encoder,
        *,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        revision: str | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        """Embed the corpus, or load its embeddings from the cache.

        Args:
            chunks: The corpus to search; must not be empty.
            encoder: Produces the embeddings.
            model_name: Identifies the encoder's model in the cache file name,
                so two models never share a cache file.
            revision: The model's Hub commit, also part of the cache file name,
                so updated weights never reuse old vectors.
            cache_dir: Directory for the embedding cache; ``None`` disables it.

        Raises:
            InvalidDomainObjectError: If ``chunks`` is empty or the encoder
                returns the wrong number of rows.
        """
        if not chunks:
            raise InvalidDomainObjectError("DenseRetriever needs at least one chunk")
        self._chunks = tuple(chunks)
        self._encoder = encoder
        passages = [PASSAGE_PREFIX + chunk.text for chunk in self._chunks]
        self._cache_path = (
            None
            if cache_dir is None
            else cache_dir / f"{_slug(model_name, revision)}-"
            f"{corpus_fingerprint(self._chunks, passages)}.npy"
        )
        self._matrix = self._load_or_embed(passages)

    @classmethod
    def from_chunks(
        cls,
        chunks: Sequence[Chunk],
        *,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        revision: str | None = DEFAULT_EMBEDDING_REVISION,
        cache_dir: Path | None = DEFAULT_CACHE_DIR,
        device: str | None = None,
    ) -> "DenseRetriever":
        """Build a retriever backed by a real sentence-transformers model.

        Args:
            chunks: The corpus to search.
            model_name: Hugging Face id of an E5-style model.
            revision: Hub commit to load; pinned to the measured one by default.
            cache_dir: Directory for the embedding cache; ``None`` disables it.
            device: Torch device; picked automatically if ``None``.
        """
        encoder = SentenceTransformerEncoder(model_name, revision=revision, device=device)
        return cls(chunks, encoder, model_name=model_name, revision=revision, cache_dir=cache_dir)

    @property
    def name(self) -> str:
        """Always ``"dense"``."""
        return "dense"

    @property
    def cache_path(self) -> Path | None:
        """The cache file used for this corpus and model, if caching is on."""
        return self._cache_path

    def search(self, query: str, k: int) -> list[Hit]:
        """Return the ``k`` chunks closest to ``query``, best first.

        Equal scores keep corpus order, so results are reproducible.
        """
        if k < 1:
            return []
        query_vector = _unit_rows(self._encode([QUERY_PREFIX + query.strip()], expected=1))[0]
        scores = self._matrix @ query_vector
        # A stable sort on the negated scores keeps corpus order among ties.
        top = np.argsort(-scores, kind="stable")[:k]
        return [
            Hit(self._chunks[index], float(scores[index]), rank, self.name)
            for rank, index in enumerate(top.tolist(), start=1)
        ]

    def _load_or_embed(self, passages: list[str]) -> Embeddings:
        path = self._cache_path
        if path is not None and path.exists():
            try:
                cached = np.load(path, allow_pickle=False)
            except (OSError, ValueError) as error:
                # A cache is disposable: a damaged file costs one re-embedding.
                _log.warning("Ignoring unreadable embedding cache %s: %s", path, error)
            else:
                # The fingerprint already pins the content; the shape check only
                # guards against a file written by something else under that name.
                if cached.ndim == 2 and cached.shape[0] == len(passages):  # noqa: PLR2004
                    return np.asarray(cached, dtype=np.float32)
        matrix = _unit_rows(self._encode(passages, expected=len(passages)))
        if path is not None:
            _save_atomically(path, matrix)
        return matrix

    def _encode(self, texts: list[str], expected: int) -> Embeddings:
        vectors = np.asarray(self._encoder.encode(texts), dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[0] != expected:  # noqa: PLR2004 - a matrix
            raise InvalidDomainObjectError(
                f"Encoder returned shape {vectors.shape} for {expected} texts"
            )
        return vectors


def corpus_fingerprint(chunks: Sequence[Chunk], texts: Sequence[str]) -> str:
    """SHA-256 over every chunk id and the exact text embedded for it (first 16 hex digits).

    Hashing the embedded strings, prefix included, rather than the chunks means
    that changing what is embedded also invalidates the cache.

    Args:
        chunks: The corpus, in index order.
        texts: The string embedded for each chunk.
    """
    digest = hashlib.sha256()
    for chunk, text in zip(chunks, texts, strict=True):
        # Unit and record separators cannot occur in ids or law text, so two
        # different corpora can never serialize to the same byte stream.
        digest.update(f"{chunk.chunk_id}\x1f{text}\x1e".encode())
    return digest.hexdigest()[:16]


def _slug(model_name: str, revision: str | None = None) -> str:
    name = model_name if revision is None else f"{model_name}@{revision[:12]}"
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _unit_rows(matrix: Embeddings) -> Embeddings:
    # Normalizing here, not trusting the encoder, makes the dot product a cosine
    # similarity for any encoder. Zero rows stay zero instead of becoming NaN.
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.asarray(matrix / np.where(norms == 0, 1, norms), dtype=np.float32)


def _save_atomically(path: Path, matrix: Embeddings) -> None:
    # Write to a temporary file and rename, so an interrupted run never leaves
    # a truncated cache that a later run would trust.
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=path.parent, suffix=".partial")
    try:
        with os.fdopen(handle, "wb") as file:
            np.save(file, matrix, allow_pickle=False)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
