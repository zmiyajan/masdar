"""Tokenization, stopwords and light stemming for lexical retrieval.

BM25 matches whole tokens, so how text is cut into tokens decides what can
match. Arabic attaches the article, conjunctions and prepositions to the word
(``والعامل``, ``بالأجر``) and marks gender, number and possession with
suffixes (``العاملة``, ``العاملين``, ``أجره``). A light stemmer strips the most
frequent of these affixes so that inflected forms of one word meet.

Light stemming follows Larkey, Ballesteros & Connell (2002), "light10", which
beat root stemming (Khoja) on TREC Arabic retrieval: roots merge too many
distinct words, which hurts precision in legal text. The rules, applied in
this order:

1. Remove ``و`` ("and") if at least 3 characters remain.
2. Remove one definite-article prefix (``وال بال كال فال لل ال``, longest
   first) if at least 2 characters remain.
3. Walk the suffix list once, in the paper's order (``ها ان ات ون ين يه ية ه
   ة ي``), removing each suffix found at the end if at least 2 characters
   remain. Several suffixes can go (``عمالها`` → ``عمال``).

Everything here works on text that has already been through
`masdar.domain.arabic.ArabicNormalizer`. The default normalizer folds ``ة`` into
``ه``, so the ``ية`` and ``ة`` suffixes never fire there; they stay in the list
so the stemmer is also correct for text normalized without that folding.

The choices and their measured effect are in
``docs/decisions/0006-lexical-retrieval-and-evaluation.md``.
"""

import re
from dataclasses import dataclass

from masdar.domain.arabic import normalize_arabic

# Runs of letters and digits. ``\w`` alone would also keep ``_``, which never
# joins two Arabic words, so it is excluded and acts as a separator.
_TOKEN = re.compile(r"[^\W_]+")

_WAW = "و"
# Longest first, so ``بال`` wins over a shorter overlapping prefix.
_DEFINITE_ARTICLES = ("وال", "بال", "كال", "فال", "لل", "ال")
# The paper's order; it matters because each suffix is tried exactly once.
_SUFFIXES = ("ها", "ان", "ات", "ون", "ين", "يه", "ية", "ه", "ة", "ي")
# Larkey et al.: "و" only if 3 characters remain; everything else needs 2.
_MIN_AFTER_WAW = 3
_MIN_STEM = 2

# Function words that carry no topic: prepositions, conjunctions, pronouns,
# relative and interrogative particles, and auxiliaries that questions add
# (``هل``، ``ما``، ``يجوز``) but articles rarely contain. Content words, even
# dialect ones such as ``لازم``, are kept on purpose. Written in standard
# spelling and passed through the default normalizer below, so ``على`` becomes
# ``علي`` and ``إلى`` becomes ``الي``, exactly as they appear in indexed text.
_STOPWORDS_SOURCE = """
في من على إلى عن مع إلا حتى منذ لدى عند بين دون ضد نحو خلال
و أو أم ثم بل لكن ف ب ل ك
أن إن كان كانت يكون تكون ليس ليست قد لقد لم لن لا ما ماذا هل كيف متى أين كم لماذا أي
هذا هذه ذلك تلك هؤلاء أولئك هنا هناك
الذي التي الذين اللذان اللتان اللاتي اللواتي
هو هي هم هن هما أنا نحن أنت أنتم
كل بعض غير أيضا إذا إذ لو كما مثل حيث وفق
عليه عليها عليهم فيه فيها فيهم منه منها منهم له لها لهم به بها بهم
"""
STOPWORDS = frozenset(normalize_arabic(word) for word in _STOPWORDS_SOURCE.split())
"""Normalized Arabic function words dropped when ``TokenizerOptions.stopwords`` is on."""


@dataclass(frozen=True, slots=True)
class TokenizerOptions:
    """Switches for the lexical analysis; each one is measured in the evaluation.

    Both default to on. Stopword removal only pays off together with stemming:
    light10 turns function words into short pseudo-stems (``علي`` → ``عل``,
    ``يكون`` → ``يك``) that collide with real stems, so they are dropped first.

    Attributes:
        stopwords: Drop the function words in `STOPWORDS`.
        stemming: Apply the light10 stemmer (`light_stem`) to every token.
    """

    stopwords: bool = True
    stemming: bool = True


def light_stem(token: str) -> str:
    """Strip common Arabic prefixes and suffixes (light10, Larkey et al. 2002).

    The minimum-length guards mean a stem never drops below two characters,
    so short words such as ``ان`` or ``له`` are left alone.

    Args:
        token: One normalized token.

    Returns:
        The stem; never empty for a non-empty token.

    Example:
        >>> [light_stem(w) for w in ("والعمال", "بالاجر", "العاملين", "عقده")]
        ['عمال', 'اجر', 'عامل', 'عقد']
    """
    if token.startswith(_WAW) and len(token) - len(_WAW) >= _MIN_AFTER_WAW:
        token = token[len(_WAW) :]
    for prefix in _DEFINITE_ARTICLES:
        if token.startswith(prefix) and len(token) - len(prefix) >= _MIN_STEM:
            token = token[len(prefix) :]
            break
    for suffix in _SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= _MIN_STEM:
            token = token[: -len(suffix)]
    return token


class ArabicTokenizer:
    """Turns normalized text into the tokens BM25 indexes.

    Example:
        >>> ArabicTokenizer().tokenize("ما حقوق العامل؟")
        ['حقوق', 'عامل']
    """

    __slots__ = ("_options",)

    def __init__(self, options: TokenizerOptions | None = None) -> None:
        """Create a tokenizer.

        Args:
            options: Analysis switches. Defaults to `TokenizerOptions()`.
        """
        self._options = options or TokenizerOptions()

    @property
    def options(self) -> TokenizerOptions:
        """The switches this tokenizer was built with."""
        return self._options

    def tokenize(self, text: str) -> list[str]:
        """Split ``text`` on non-word characters, then filter and stem.

        Stopwords are removed *before* stemming: the list holds surface forms,
        and stemming first would turn some of them into other words' stems.

        Args:
            text: Text already normalized by `ArabicNormalizer`.

        Returns:
            Non-empty tokens in reading order.
        """
        tokens = _TOKEN.findall(text)
        if self._options.stopwords:
            tokens = [token for token in tokens if token not in STOPWORDS]
        if self._options.stemming:
            tokens = [light_stem(token) for token in tokens]
        return tokens
