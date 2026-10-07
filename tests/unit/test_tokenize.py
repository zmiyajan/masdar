"""Tests for the Arabic tokenizer, stopword list and light10 stemmer."""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from masdar.domain.arabic import normalize_arabic
from masdar.domain.tokenize import STOPWORDS, ArabicTokenizer, TokenizerOptions, light_stem

ARABIC_LETTERS = st.characters(min_codepoint=0x0621, max_codepoint=0x064A)
WORDS = st.text(alphabet=ARABIC_LETTERS, min_size=1, max_size=12)


class TestLightStem:
    @pytest.mark.parametrize(
        ("word", "stem"),
        [
            pytest.param("العامل", "عامل", id="definite-article"),
            pytest.param("والعامل", "عامل", id="waw-then-article"),
            pytest.param("بالاجر", "اجر", id="bi-al"),
            pytest.param("للعامل", "عامل", id="lil"),
            pytest.param("فالعقد", "عقد", id="fa-al"),
            pytest.param("كالعقد", "عقد", id="ka-al"),
            pytest.param("العاملين", "عامل", id="plural-yn"),
            pytest.param("العاملون", "عامل", id="plural-wn"),
            pytest.param("الاجازات", "اجاز", id="feminine-plural"),
            pytest.param("عقده", "عقد", id="pronoun-h"),
            pytest.param("اجرها", "اجر", id="pronoun-ha"),
            pytest.param("العماليه", "عمال", id="nisba-yh"),
            pytest.param("المسؤولية", "مسؤول", id="unfolded-taa-marbuta"),
        ],
    )
    def test_strips_light10_affixes(self, word: str, stem: str) -> None:
        assert light_stem(word) == stem

    @pytest.mark.parametrize(
        "word",
        [
            pytest.param("وعد", id="waw-would-leave-two"),
            pytest.param("الم", id="article-would-leave-one"),
            pytest.param("له", id="suffix-would-leave-one"),
            pytest.param("في", id="two-letters"),
        ],
    )
    def test_minimum_length_guards_keep_short_words(self, word: str) -> None:
        assert light_stem(word) == word

    def test_suffixes_are_tried_once_in_order(self) -> None:
        # ها is checked before ه, so the whole pronoun goes, not just its last letter.
        assert light_stem("عمالها") == "عمال"

    @given(WORDS)
    def test_a_stem_is_never_empty_or_longer(self, word: str) -> None:
        stem = light_stem(word)
        assert stem
        assert len(stem) <= len(word)
        assert stem in word


class TestStopwords:
    def test_list_is_in_normalized_form(self) -> None:
        assert all(normalize_arabic(word) == word for word in STOPWORDS)

    def test_holds_question_function_words(self) -> None:
        assert {"في", "من", "علي", "ان", "ما", "هل", "التي", "الذي", "الي"} <= STOPWORDS

    def test_keeps_content_words(self) -> None:
        assert not {"عامل", "اجر", "عقد", "لازم"} & STOPWORDS


class TestArabicTokenizer:
    def test_splits_on_punctuation_and_drops_function_words(self) -> None:
        tokens = ArabicTokenizer().tokenize("هل يحق للعامل، في فتره التجربه، الاجازه؟")
        assert tokens == ["يحق", "عامل", "فتر", "تجرب", "اجاز"]

    def test_keeps_digits_as_tokens(self) -> None:
        assert ArabicTokenizer().tokenize("الماده 79") == ["ماد", "79"]

    def test_underscore_separates_tokens(self) -> None:
        options = TokenizerOptions(stopwords=False, stemming=False)
        assert ArabicTokenizer(options).tokenize("عقد_عمل") == ["عقد", "عمل"]

    def test_switches_off(self) -> None:
        tokenizer = ArabicTokenizer(TokenizerOptions(stopwords=False, stemming=False))
        assert tokenizer.tokenize("ما هي العقوبات") == ["ما", "هي", "العقوبات"]
        assert tokenizer.options == TokenizerOptions(stopwords=False, stemming=False)

    def test_stopwords_are_removed_before_stemming(self) -> None:
        # "الذي" would stem to "ذي"; it must be dropped as a stopword instead.
        assert ArabicTokenizer().tokenize("الذي") == []

    @given(
        st.text(alphabet=st.one_of(ARABIC_LETTERS, st.sampled_from(" ،؟.:_-\n0123456789ab"))),
        st.booleans(),
        st.booleans(),
    )
    def test_never_produces_empty_or_split_tokens(
        self, text: str, stopwords: bool, stemming: bool
    ) -> None:
        options = TokenizerOptions(stopwords=stopwords, stemming=stemming)
        for token in ArabicTokenizer(options).tokenize(normalize_arabic(text)):
            assert token
            assert token.isalnum()
