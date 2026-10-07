"""Tests for the dense retriever and its embedding cache, on a fake encoder."""

from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pytest

from masdar.adapters.dense import (
    DEFAULT_CACHE_DIR,
    DEFAULT_EMBEDDING_MODEL,
    PASSAGE_PREFIX,
    QUERY_PREFIX,
    DenseRetriever,
    Embeddings,
    corpus_fingerprint,
)
from masdar.domain.amendments import ArticleStatus
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article, Chunk
from masdar.domain.ordinals import ArticleNumber

# Each known word maps to one axis, so similarity is easy to predict by hand.
VOCABULARY = ("اجازة", "اجر", "عقد", "تجربة")


def chunk(number: int, text: str) -> Chunk:
    article = Article(
        "labor-law",
        "نظام العمل",
        ArticleNumber(number),
        f"المادة {number}",
        text,
        ArticleStatus.IN_FORCE,
    )
    return Chunk(f"labor-law:{number}#0", article, text, f"normalized {text}")


class BagOfWordsEncoder:
    """Deterministic fake: counts known words; records every call."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: Sequence[str]) -> Embeddings:
        self.calls.append(list(texts))
        return np.array(
            [[float(text.split().count(word)) for word in VOCABULARY] for text in texts],
            dtype=np.float32,
        )


CHUNKS = (
    chunk(1, "اجازة اجازة اجر"),
    chunk(2, "عقد تجربة"),
    chunk(3, "اجر"),
)


def test_defaults() -> None:
    assert DEFAULT_EMBEDDING_MODEL == "intfloat/multilingual-e5-small"
    assert Path("data/index") == DEFAULT_CACHE_DIR


def test_embeds_display_text_with_e5_prefixes() -> None:
    encoder = BagOfWordsEncoder()
    retriever = DenseRetriever(CHUNKS, encoder)
    retriever.search("  اجازة ", 1)
    passages, queries = encoder.calls
    assert passages == [PASSAGE_PREFIX + c.text for c in CHUNKS]
    assert queries == [QUERY_PREFIX + "اجازة"]
    assert retriever.name == "dense"


def test_ranks_by_cosine_similarity() -> None:
    hits = DenseRetriever(CHUNKS, BagOfWordsEncoder()).search("اجازة اجر", 3)
    assert [hit.chunk.chunk_id for hit in hits] == [
        "labor-law:1#0",  # (2,1) vs (1,1): cos = 3 / sqrt(10)
        "labor-law:3#0",  # (0,1) vs (1,1): cos = 1 / sqrt(2)
        "labor-law:2#0",  # orthogonal
    ]
    assert [hit.rank for hit in hits] == [1, 2, 3]
    assert hits[0].score == pytest.approx(3 / np.sqrt(10))
    assert hits[1].score == pytest.approx(1 / np.sqrt(2))
    assert hits[2].score == pytest.approx(0.0)
    assert all(isinstance(hit.score, float) for hit in hits)


def test_ties_keep_corpus_order() -> None:
    tied = (chunk(5, "عقد"), chunk(4, "عقد"), chunk(6, "عقد"))
    hits = DenseRetriever(tied, BagOfWordsEncoder()).search("عقد", 3)
    assert [hit.chunk.chunk_id for hit in hits] == [c.chunk_id for c in tied]


def test_k_bounds() -> None:
    retriever = DenseRetriever(CHUNKS, BagOfWordsEncoder())
    assert len(retriever.search("اجر", 10)) == len(CHUNKS)
    assert retriever.search("اجر", 0) == []


def test_unknown_words_give_zero_scores_not_nan() -> None:
    hits = DenseRetriever(CHUNKS, BagOfWordsEncoder()).search("كلمة", 3)
    assert [hit.score for hit in hits] == [0.0, 0.0, 0.0]


def test_rejects_an_empty_corpus() -> None:
    with pytest.raises(InvalidDomainObjectError, match="at least one chunk"):
        DenseRetriever([], BagOfWordsEncoder())


def test_rejects_an_encoder_returning_the_wrong_shape() -> None:
    class Broken:
        def encode(self, texts: Sequence[str]) -> Embeddings:
            return np.zeros((len(texts) + 1, 2), dtype=np.float32)

    with pytest.raises(InvalidDomainObjectError, match="Encoder returned"):
        DenseRetriever(CHUNKS, Broken())


class TestCache:
    def test_without_cache_dir_nothing_is_written(self, tmp_path: Path) -> None:
        retriever = DenseRetriever(CHUNKS, BagOfWordsEncoder())
        assert retriever.cache_path is None
        assert list(tmp_path.iterdir()) == []

    def test_second_build_reuses_the_cache(self, tmp_path: Path) -> None:
        first = BagOfWordsEncoder()
        built = DenseRetriever(CHUNKS, first, model_name="org/Model-X", cache_dir=tmp_path)
        assert built.cache_path is not None
        assert built.cache_path.parent == tmp_path
        assert built.cache_path.name.startswith("org-model-x-")
        assert built.cache_path.suffix == ".npy"
        assert len(first.calls) == 1

        second = BagOfWordsEncoder()
        reused = DenseRetriever(CHUNKS, second, model_name="org/Model-X", cache_dir=tmp_path)
        assert second.calls == []
        assert reused.cache_path == built.cache_path
        query = "اجازة اجر"
        assert reused.search(query, 3) == built.search(query, 3)
        assert [p.name for p in tmp_path.iterdir()] == [built.cache_path.name]

    def test_a_text_change_invalidates_the_cache(self, tmp_path: Path) -> None:
        old = DenseRetriever(CHUNKS, BagOfWordsEncoder(), cache_dir=tmp_path)
        edited = (chunk(1, "اجازة"), *CHUNKS[1:])
        encoder = BagOfWordsEncoder()
        new = DenseRetriever(edited, encoder, cache_dir=tmp_path)
        assert len(encoder.calls) == 1
        assert new.cache_path != old.cache_path

    def test_a_different_model_never_shares_a_file(self, tmp_path: Path) -> None:
        small = DenseRetriever(CHUNKS, BagOfWordsEncoder(), model_name="a/s", cache_dir=tmp_path)
        base = DenseRetriever(CHUNKS, BagOfWordsEncoder(), model_name="a/b", cache_dir=tmp_path)
        assert small.cache_path != base.cache_path

    def test_a_new_model_revision_never_reuses_old_vectors(self, tmp_path: Path) -> None:
        old = DenseRetriever(CHUNKS, BagOfWordsEncoder(), revision="aaaa1111", cache_dir=tmp_path)
        new = DenseRetriever(CHUNKS, BagOfWordsEncoder(), revision="bbbb2222", cache_dir=tmp_path)
        assert old.cache_path != new.cache_path

    def test_an_unreadable_file_is_rebuilt(self, tmp_path: Path) -> None:
        built = DenseRetriever(CHUNKS, BagOfWordsEncoder(), cache_dir=tmp_path)
        assert built.cache_path is not None
        built.cache_path.write_bytes(b"not a numpy file")
        encoder = BagOfWordsEncoder()
        DenseRetriever(CHUNKS, encoder, cache_dir=tmp_path)
        assert len(encoder.calls) == 1
        assert np.load(built.cache_path).shape == (len(CHUNKS), len(VOCABULARY))

    def test_a_mismatched_file_is_rebuilt(self, tmp_path: Path) -> None:
        built = DenseRetriever(CHUNKS, BagOfWordsEncoder(), cache_dir=tmp_path)
        assert built.cache_path is not None
        np.save(built.cache_path, np.zeros((1, 4), dtype=np.float32))
        encoder = BagOfWordsEncoder()
        DenseRetriever(CHUNKS, encoder, cache_dir=tmp_path)
        assert len(encoder.calls) == 1
        assert np.load(built.cache_path).shape == (len(CHUNKS), len(VOCABULARY))

    def test_creates_the_directory_and_leaves_no_partial_file(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "nested" / "index"
        DenseRetriever(CHUNKS, BagOfWordsEncoder(), cache_dir=cache_dir)
        assert [p.suffix for p in cache_dir.iterdir()] == [".npy"]

    def test_a_failed_write_cleans_up(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def fail(*_: object, **__: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(np, "save", fail)
        with pytest.raises(OSError, match="disk full"):
            DenseRetriever(CHUNKS, BagOfWordsEncoder(), cache_dir=tmp_path)
        assert list(tmp_path.iterdir()) == []


class TestFingerprint:
    def test_is_stable_and_short(self) -> None:
        texts = [c.text for c in CHUNKS]
        assert corpus_fingerprint(CHUNKS, texts) == corpus_fingerprint(CHUNKS, texts)
        assert len(corpus_fingerprint(CHUNKS, texts)) == 16

    def test_depends_on_ids_texts_and_order(self) -> None:
        texts = [c.text for c in CHUNKS]
        base = corpus_fingerprint(CHUNKS, texts)
        assert corpus_fingerprint(CHUNKS, [*texts[:-1], "other"]) != base
        assert corpus_fingerprint(CHUNKS[::-1], texts[::-1]) != base
        renamed = (chunk(9, CHUNKS[0].text), *CHUNKS[1:])
        assert corpus_fingerprint(renamed, texts) != base
