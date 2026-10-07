"""Tests for the BM25 retriever on a tiny in-memory corpus."""

from itertools import permutations

import pytest

from masdar.adapters.bm25 import (
    Bm25Retriever,
    arabic_analyzer,
    display_text,
    whitespace_analyzer,
)
from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article, Chunk
from masdar.domain.ordinals import ArticleNumber
from masdar.domain.tokenize import ArabicTokenizer, TokenizerOptions

TEXTS = {
    1: "لا يجوز أن تزيد فترة التجربة على تسعين يوماً",
    2: "يستحق العامل أجراً عن ساعات العمل الإضافية",
    3: "للعامل الحق في إجازة سنوية بأجر",
    4: "تنتهي علاقة العمل بوفاة العامل",
}


def make_chunk(number: int, text: str) -> Chunk:
    article = Article("labor-law", "نظام العمل", ArticleNumber(number), f"المادة {number}", text)
    return Chunk(f"labor-law:{number}#0", article, text, ArabicNormalizer().normalize(text))


@pytest.fixture
def chunks() -> list[Chunk]:
    return [make_chunk(number, text) for number, text in TEXTS.items()]


def ids(retriever: Bm25Retriever, query: str, k: int = 10) -> list[str]:
    return [hit.chunk.chunk_id for hit in retriever.search(query, k)]


class TestBm25Retriever:
    def test_ranks_the_matching_chunk_first(self, chunks: list[Chunk]) -> None:
        hits = Bm25Retriever(chunks).search("كم مدة فترة التجربة؟", 10)
        assert hits[0].chunk.chunk_id == "labor-law:1#0"
        assert [hit.rank for hit in hits] == list(range(1, len(hits) + 1))
        assert all(hit.retriever == "bm25" for hit in hits)
        assert hits == sorted(hits, key=lambda hit: -hit.score)

    def test_stemming_matches_inflected_forms(self, chunks: list[Chunk]) -> None:
        # The query says "الإجازات" (plural); the article says "إجازة".
        assert ids(Bm25Retriever(chunks), "الإجازات")[:1] == ["labor-law:3#0"]
        unstemmed = arabic_analyzer(tokenizer=ArabicTokenizer(TokenizerOptions(stemming=False)))
        assert ids(Bm25Retriever(chunks, analyzer=unstemmed), "الإجازات") == []

    def test_drops_non_matching_chunks(self, chunks: list[Chunk]) -> None:
        assert ids(Bm25Retriever(chunks), "التجربة") == ["labor-law:1#0"]

    @pytest.mark.parametrize("query", ["هل في من", "؟؟", "شركة مساهمة"])
    def test_no_hits_for_stopwords_punctuation_or_unknown_words(
        self, chunks: list[Chunk], query: str
    ) -> None:
        assert Bm25Retriever(chunks).search(query, 10) == []

    def test_respects_k(self, chunks: list[Chunk]) -> None:
        retriever = Bm25Retriever(chunks)
        assert len(retriever.search("العامل", 1)) == 1
        assert retriever.search("العامل", 0) == []

    def test_ties_are_broken_by_chunk_id_whatever_the_corpus_order(self) -> None:
        same = [make_chunk(number, "نص مكرر") for number in (3, 1, 2)]
        filler = [make_chunk(9, "كلام آخر تماما"), make_chunk(8, "كلام مختلف أيضا")]
        expected = ["labor-law:1#0", "labor-law:2#0", "labor-law:3#0"]
        for corpus in permutations(same + filler):
            assert ids(Bm25Retriever(corpus), "مكرر") == expected

    def test_raw_baseline_indexes_display_text_with_whitespace_tokens(
        self, chunks: list[Chunk]
    ) -> None:
        raw = Bm25Retriever(
            chunks, name="bm25-raw", analyzer=whitespace_analyzer, text_of=display_text
        )
        assert raw.name == "bm25-raw"
        # Unnormalized: the hamza spelling must match exactly.
        assert ids(raw, "أجراً") == ["labor-law:2#0"]
        assert ids(raw, "اجرا") == []

    def test_rejects_an_empty_corpus(self) -> None:
        with pytest.raises(InvalidDomainObjectError):
            Bm25Retriever([])
