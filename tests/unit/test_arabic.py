"""Tests for the Arabic normalizer.

Example-based tests pin down each rule; property-based tests (Hypothesis) check
guarantees that must hold for *any* input, including text nobody thought of.
The generators are biased towards Arabic: plain ``st.text()`` almost never
produces Arabic code points, so it would leave the interesting cases untested.
"""

from concurrent.futures import ThreadPoolExecutor

import pytest
from hypothesis import given
from hypothesis import strategies as st

from masdar.domain.arabic import (
    DIACRITICS,
    INVISIBLE,
    TATWEEL,
    ArabicNormalizer,
    NormalizationOptions,
    normalize_arabic,
)

ZWNJ, RLM, ALM, NBSP = chr(0x200C), chr(0x200F), chr(0x061C), chr(0x00A0)
HAMZA_ABOVE = chr(0x0654)
REMOVED = DIACRITICS | INVISIBLE | {TATWEEL}

arabic_text = st.text(
    alphabet=st.one_of(
        st.characters(min_codepoint=0x0600, max_codepoint=0x06FF),  # Arabic block
        st.characters(min_codepoint=0x08A0, max_codepoint=0x08FF),  # Arabic Extended-A
        st.characters(min_codepoint=0xFB50, max_codepoint=0xFEFF),  # presentation forms
        st.sampled_from([*sorted(INVISIBLE), " ", "\n", NBSP]),
        st.characters(min_codepoint=0x20, max_codepoint=0x7E),  # ASCII
    )
)
any_options = st.builds(NormalizationOptions)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param("الْعَمَلُ", "العمل", id="strips-harakat"),
        pytest.param("مُدَّة", "مده", id="strips-shadda-and-folds-taa-marbuta"),
        pytest.param("العـــمل", "العمل", id="removes-tatweel"),
        pytest.param("أجر إجازة آخر ٱلعامل", "اجر اجازه اخر العامل", id="folds-alef-variants"),
        pytest.param("مستشفى", "مستشفي", id="folds-alef-maqsura"),
        pytest.param("المادة ٧٤ و۱۲", "الماده 74 و12", id="arabic-indic-digits-to-latin"),
        pytest.param("ﻻ يجوز", "لا يجوز", id="nfkc-expands-presentation-forms"),
        pytest.param(f"ا{HAMZA_ABOVE}جر", "اجر", id="nfkc-composes-then-folds-hamza"),
        pytest.param(f"نظام{ZWNJ}العمل{RLM}", "نظامالعمل", id="drops-bidi-controls"),
        pytest.param(f"{ALM}العمل", "العمل", id="drops-arabic-letter-mark"),
        pytest.param(f"  نظام \n\t العمل{NBSP} ", "نظام العمل", id="collapses-whitespace"),
        pytest.param("Labor Law 2005", "Labor Law 2005", id="latin-text-untouched"),
        pytest.param("", "", id="empty-string"),
    ],
)
def test_default_rules(raw: str, expected: str) -> None:
    assert normalize_arabic(raw) == expected


def test_hamza_carriers_are_kept_by_default() -> None:
    # Folding ؤ/ئ merges unrelated words (e.g. مسؤول vs. مسول), so it is opt-in.
    assert normalize_arabic("مسؤولية رئيس") == "مسؤوليه رئيس"


def test_options_switch_individual_rules() -> None:
    normalizer = ArabicNormalizer(
        NormalizationOptions(
            fold_alef=False,
            fold_alef_maqsura=False,
            fold_taa_marbuta=False,
            fold_hamza_carriers=True,
            latin_digits=False,
        )
    )
    assert normalizer.normalize("أجرة مستشفى مسؤول ٧") == "أجرة مستشفى مسوول ٧"


def test_alef_kept_when_folding_is_off_even_if_composed_by_nfkc() -> None:
    normalizer = ArabicNormalizer(NormalizationOptions(fold_alef=False))
    assert normalizer.normalize(f"ا{HAMZA_ABOVE}جر") == "أجر"


def test_options_are_read_only() -> None:
    normalizer = ArabicNormalizer()
    assert normalizer.options == NormalizationOptions()
    with pytest.raises(AttributeError):
        normalizer.options = NormalizationOptions(fold_alef=False)  # type: ignore[misc]


def test_shared_instance_is_thread_safe() -> None:
    normalizer = ArabicNormalizer()
    texts = ["الْعَمَلُ", "أجر", "مُدَّة"] * 200
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(normalizer.normalize, texts))
    assert results == [normalizer.normalize(t) for t in texts]


@given(arabic_text, any_options)
def test_is_idempotent_for_every_option_combination(
    text: str, options: NormalizationOptions
) -> None:
    normalizer = ArabicNormalizer(options)
    once = normalizer.normalize(text)
    assert normalizer.normalize(once) == once


@given(arabic_text, any_options)
def test_output_never_contains_removed_characters(text: str, options: NormalizationOptions) -> None:
    assert not set(ArabicNormalizer(options).normalize(text)) & REMOVED


@given(arabic_text)
def test_output_has_no_edge_or_repeated_whitespace(text: str) -> None:
    result = normalize_arabic(text)
    assert result == result.strip()
    assert "  " not in result


@given(st.text(alphabet=st.characters(min_codepoint=0x21, max_codepoint=0x7E)))
def test_printable_ascii_without_spaces_passes_through(text: str) -> None:
    assert normalize_arabic(text) == text
