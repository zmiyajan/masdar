"""Tests for structure-aware chunking."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.chunking import ChunkingOptions, chunk_article, context_line, split_text
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article
from masdar.domain.ordinals import ArticleNumber

NORMALIZER = ArabicNormalizer()


def make_article(text: str, **overrides: object) -> Article:
    fields: dict[str, object] = {
        "law_id": "labor-law",
        "law_title": "نظام العمل",
        "number": ArticleNumber(80),
        "heading": "المادة الثمانون",
        "text": text,
        "part": "الباب الخامس",
        "chapter": "الفصل الثالث",
    }
    fields.update(overrides)
    return Article(**fields)  # type: ignore[arg-type]


def test_short_article_is_one_chunk_with_context_in_search_text_only() -> None:
    [chunk] = chunk_article(make_article("لا يجوز لصاحب العمل فسخ العقد."), NORMALIZER)
    assert chunk.chunk_id == "labor-law:80#0"
    assert chunk.text == "لا يجوز لصاحب العمل فسخ العقد."
    assert chunk.normalized_text.startswith("نظام العمل | الباب الخامس | الفصل الثالث")
    assert "الثمانون" in chunk.normalized_text


def test_context_can_be_disabled() -> None:
    [chunk] = chunk_article(
        make_article("نص المادة"), NORMALIZER, ChunkingOptions(include_context=False)
    )
    assert chunk.normalized_text == "نص الماده"


def test_long_article_splits_on_paragraph_lines_without_cutting_them() -> None:
    paragraphs = [f"{i}- " + " ".join(["كلمة"] * 15) for i in range(1, 7)]
    chunks = chunk_article(
        make_article("\n".join(paragraphs)), NORMALIZER, ChunkingOptions(max_words=40)
    )
    assert [c.chunk_id for c in chunks] == ["labor-law:80#0", "labor-law:80#1", "labor-law:80#2"]
    rejoined = "\n".join(c.text for c in chunks).splitlines()
    assert rejoined == paragraphs  # nothing lost, nothing split mid-paragraph


def test_single_overlong_line_is_split_at_sentence_then_word_boundaries() -> None:
    sentence = " ".join(["كلمة"] * 30) + "."
    pieces = split_text(sentence + " " + sentence, max_words=25)
    assert all(len(p.split()) <= 25 for p in pieces)
    assert " ".join(pieces).split() == (sentence + " " + sentence).split()


def test_context_line_skips_missing_parts() -> None:
    article = make_article("نص", part=None, chapter=None, title="التعريفات")
    assert context_line(article) == "نظام العمل | المادة الثمانون | التعريفات"


def test_rejects_tiny_budgets() -> None:
    with pytest.raises(InvalidDomainObjectError):
        ChunkingOptions(max_words=5)


words = st.text(alphabet="ابتثجحخدذرزسشصضطظعغفقكلمنهوي", min_size=1, max_size=8)
lines = st.lists(words, min_size=1, max_size=60).map(" ".join)


@given(st.lists(lines, min_size=1, max_size=12), st.integers(min_value=20, max_value=80))
def test_split_never_loses_words_and_respects_the_budget(
    paragraphs: list[str], budget: int
) -> None:
    text = "\n".join(paragraphs)
    pieces = split_text(text, budget)
    assert " ".join(pieces).split() == text.split()
    assert all(len(piece.split()) <= budget for piece in pieces)
