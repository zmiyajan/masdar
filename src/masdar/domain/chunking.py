"""Structure-aware chunking of articles.

An article is the natural retrieval unit for law: it is what gets cited. Most
articles are short (median about 50 words), so most become one chunk. Long
articles (definitions, penalty tables) are split on their own line breaks,
which separate numbered paragraphs, so a chunk never cuts a clause in half.

Each chunk's *search* text is prefixed with its context: law, part, chapter,
heading and title. This is the idea behind Contextual Retrieval (Anthropic,
2024), done here without an LLM because the context is already in the law's
structure. It lets "مدة الإشعار في نظام العمل" match an article whose own text
never says "نظام العمل". The *display* text stays the article's own words.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article, Chunk

_SENTENCE_END = re.compile(r"(?<=[.؛;:])\s+")


@dataclass(frozen=True, slots=True)
class ChunkingOptions:
    """Chunking parameters.

    Attributes:
        max_words: Upper bound on words per chunk (context prefix excluded).
        include_context: Prefix the search text with law/part/chapter/heading.
    """

    max_words: int = 300
    include_context: bool = True

    def __post_init__(self) -> None:
        """A tiny budget would shred articles into meaningless fragments."""
        if self.max_words < 20:  # noqa: PLR2004 - documented lower bound
            raise InvalidDomainObjectError(f"max_words must be >= 20, got {self.max_words}")


def chunk_article(
    article: Article,
    normalizer: ArabicNormalizer,
    options: ChunkingOptions | None = None,
) -> list[Chunk]:
    """Split one article into chunks ready for indexing.

    Args:
        article: The article to split.
        normalizer: Produces the search text.
        options: Chunking parameters; defaults to `ChunkingOptions()`.

    Returns:
        One or more chunks, ids ``"<article_id>#<index>"`` in reading order.
    """
    opts = options or ChunkingOptions()
    context = context_line(article) if opts.include_context else ""
    return [
        Chunk(
            chunk_id=f"{article.article_id}#{index}",
            article=article,
            text=piece,
            normalized_text=normalizer.normalize(f"{context}\n{piece}" if context else piece),
        )
        for index, piece in enumerate(split_text(article.text, opts.max_words))
    ]


def context_line(article: Article) -> str:
    """The article's location in its law, e.g. ``"نظام العمل | الباب ... | المادة ..."``."""
    parts = (article.law_title, article.part, article.chapter, article.heading, article.title)
    return " | ".join(part for part in parts if part)


def split_text(text: str, max_words: int) -> list[str]:
    r"""Pack lines into pieces of at most ``max_words`` words.

    Lines are kept whole when they fit; a single over-long line is split at
    sentence ends, and only as a last resort at word boundaries.

    Example:
        >>> split_text("1- أ\n2- ب", max_words=300)
        ['1- أ\n2- ب']
    """
    pieces: list[str] = []
    current: list[str] = []
    current_words = 0
    for unit in _units(text, max_words):
        words = len(unit.split())
        if current and current_words + words > max_words:
            pieces.append("\n".join(current))
            current, current_words = [], 0
        current.append(unit)
        current_words += words
    if current:
        pieces.append("\n".join(current))
    return pieces


def _units(text: str, max_words: int) -> Iterator[str]:
    """Lines, with any line longer than ``max_words`` broken into smaller units."""
    for line in (line.strip() for line in text.splitlines()):
        if not line:
            continue
        if len(line.split()) <= max_words:
            yield line
            continue
        for sentence in _SENTENCE_END.split(line):
            yield from _word_windows(sentence, max_words)


def _word_windows(sentence: str, max_words: int) -> Iterator[str]:
    words = sentence.split()
    for start in range(0, len(words), max_words):
        yield " ".join(words[start : start + max_words])
