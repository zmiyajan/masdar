"""Arabic text normalization for retrieval.

The same word can be typed many ways in Arabic: with or without diacritics
(تشكيل), stretched with tatweel (ـ), with different alef forms (أ إ آ ا), with
Arabic-Indic or Latin digits. A search engine that compares raw strings treats
all of these as different words. Normalization folds them into one canonical
form so that a query and a document meet in the middle.

Normalization is deliberately *lossy* (e.g. ``ة`` → ``ه``), so it is applied
only to text used for matching. The original text is always kept for display
(see `masdar.domain.models.Chunk`).

The exact rules, their order, and why each is on or off by default are recorded
in ``docs/decisions/0003-arabic-normalization.md``.
"""

import re
import unicodedata
from dataclasses import dataclass

# Combining marks that never change which word is meant:
#   U+0610–U+061A  honorific and Quranic signs above/below letters
#   U+064B–U+065F  harakat, shadda, sukun, hamza/madda combining forms
#   U+0670         superscript alef
#   U+06D6–U+06ED  Quranic annotation marks
#   U+08D3–U+08FF  extended Arabic marks (Quranic and African orthographies)
DIACRITICS = frozenset(
    [chr(c) for c in range(0x0610, 0x061B)]
    + [chr(c) for c in range(0x064B, 0x0660)]
    + [chr(0x0670)]
    + [chr(c) for c in range(0x06D6, 0x06EE)]
    + [chr(c) for c in range(0x08D3, 0x0900)]
)
TATWEEL = chr(0x0640)
# Invisible format characters (Unicode category Cf) that silently break matching
# when text is copied from web pages and PDFs.
INVISIBLE = frozenset(
    [chr(0x00AD), chr(0x061C)]  # soft hyphen, Arabic letter mark
    + [chr(c) for c in range(0x200B, 0x2010)]  # ZWSP, ZWNJ, ZWJ, LRM, RLM
    + [chr(c) for c in range(0x202A, 0x202F)]  # LRE, RLE, PDF, LRO, RLO
    + [chr(c) for c in range(0x2060, 0x2065)]  # word joiner, invisible operators
    + [chr(c) for c in range(0x2066, 0x206A)]  # LRI, RLI, FSI, PDI
    + [chr(0xFEFF)]  # byte-order mark / ZWNBSP
)
_ALEF_VARIANTS = {"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"}
_ARABIC_INDIC_DIGITS = {chr(0x0660 + d): str(d) for d in range(10)}
_EXTENDED_ARABIC_INDIC_DIGITS = {chr(0x06F0 + d): str(d) for d in range(10)}

_WHITESPACE_RUN = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class NormalizationOptions:
    """Switches for the lossy letter-folding rules.

    Rules that only remove noise (invisible characters, diacritics, tatweel,
    Unicode compatibility forms, whitespace) are always applied. The options
    below change real letters, so each one can be toggled and measured in the
    retrieval evaluation.

    Attributes:
        fold_alef: ``أ إ آ ٱ`` → ``ا``.
        fold_alef_maqsura: ``ى`` → ``ي``.
        fold_taa_marbuta: ``ة`` → ``ه``.
        fold_hamza_carriers: ``ؤ`` → ``و`` and ``ئ`` → ``ي``.
        latin_digits: Arabic-Indic digits ``٠-٩`` / ``۰-۹`` → ``0-9``.
    """

    fold_alef: bool = True
    fold_alef_maqsura: bool = True
    fold_taa_marbuta: bool = True
    fold_hamza_carriers: bool = False
    latin_digits: bool = True


def _build_table(options: NormalizationOptions) -> dict[int, str | None]:
    """Build the ``str.translate`` table: removals first, then chosen foldings."""
    mapping: dict[str, str | None] = dict.fromkeys(DIACRITICS | INVISIBLE | {TATWEEL})
    if options.fold_alef:
        mapping.update(_ALEF_VARIANTS)
    if options.fold_alef_maqsura:
        mapping["ى"] = "ي"
    if options.fold_taa_marbuta:
        mapping["ة"] = "ه"
    if options.fold_hamza_carriers:
        mapping.update({"ؤ": "و", "ئ": "ي"})
    if options.latin_digits:
        mapping.update(_ARABIC_INDIC_DIGITS)
        mapping.update(_EXTENDED_ARABIC_INDIC_DIGITS)
    return str.maketrans(mapping)


class ArabicNormalizer:
    """Normalizes Arabic text into a canonical, search-friendly form.

    The translation table is built once, in the constructor, so normalizing a
    large corpus is a single C-level ``str.translate`` pass per string. Options
    are read-only after construction: the table can never drift from them, and
    an instance is safe to share between threads.

    Example:
        >>> ArabicNormalizer().normalize("الْعَمَلُ  ـــ  أَجْر")
        'العمل اجر'
    """

    __slots__ = ("_options", "_table")

    def __init__(self, options: NormalizationOptions | None = None) -> None:
        """Create a normalizer.

        Args:
            options: Letter-folding switches. Defaults to `NormalizationOptions()`.
        """
        self._options = options or NormalizationOptions()
        self._table = _build_table(self._options)

    @property
    def options(self) -> NormalizationOptions:
        """The letter-folding switches this normalizer was built with."""
        return self._options

    def normalize(self, text: str) -> str:
        """Return the normalized form of ``text``.

        Steps, in order:
            1. Unicode NFKC: turns presentation forms (common in PDF text, e.g.
               ``ﻻ``) and compatibility characters (e.g. no-break space) into
               their standard equivalents.
            2. Remove diacritics, tatweel and invisible control characters, and
               apply the letter folding chosen in `NormalizationOptions`.
            3. Collapse whitespace runs to a single space and trim the ends.

        The function is idempotent: ``normalize(normalize(t)) == normalize(t)``.

        Args:
            text: Any string; non-Arabic text passes through except for steps
                1 and 3.

        Returns:
            The normalized string.
        """
        text = unicodedata.normalize("NFKC", text)
        text = text.translate(self._table)
        return _WHITESPACE_RUN.sub(" ", text).strip()


_DEFAULT_NORMALIZER = ArabicNormalizer()


def normalize_arabic(text: str) -> str:
    """Normalize ``text`` with the default options. See `ArabicNormalizer.normalize`."""
    return _DEFAULT_NORMALIZER.normalize(text)
