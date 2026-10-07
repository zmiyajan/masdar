"""Build `Article` objects from what a publisher gives us.

A publisher adapter (e.g. the BOE HTML parser) only extracts raw pieces: the
heading, the body, the attached amendment notes, and the part/chapter. All the
legal reasoning (numbers, titles, which text is in force, articles that exist
only inside another article's amendment note) happens here, in pure code that
is tested without HTML or network.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from masdar.domain.amendments import (
    Amendment,
    AmendmentKind,
    ArticleStatus,
    parse_amendment,
    resolve,
)
from masdar.domain.models import Article
from masdar.domain.ordinals import ArticleNumber, parse_article_number

_ARTICLE_PREFIX = "المادة"
_CURRENTLY = "حالي"  # matches "حالياً" (currently) in renumbered headings
_PARENS = re.compile(r"[()]")


@dataclass(frozen=True, slots=True)
class ArticleSource:
    """One article block exactly as a publisher presents it.

    Attributes:
        heading: Heading as published, e.g. ``"المادة الأولى :"``.
        body: The article's own text as published.
        notes: Amendment notes attached to the article, in published order.
        part: The part (باب) heading in effect, if any.
        chapter: The chapter (فصل) heading in effect, if any.
    """

    heading: str
    body: str
    notes: tuple[str, ...] = ()
    part: str | None = None
    chapter: str | None = None


@dataclass(frozen=True, slots=True)
class PublishedLaw:
    """A law as fetched from a publisher, before any legal processing.

    Attributes:
        law_id: Masdar's slug for the law.
        title: Official title.
        source_url: Where the text was fetched from.
        sources: The article blocks, in published order.
        retrieved_on: ISO date the source was fetched, when known.
    """

    law_id: str
    title: str
    source_url: str
    sources: tuple[ArticleSource, ...]
    retrieved_on: str | None = None


def clean_heading(raw: str) -> str:
    """Normalize a published heading into a citation heading.

    Examples:
        >>> clean_heading("المادة الأولى :")
        'المادة الأولى'
        >>> clean_heading("( التاسعة والسبعين مكرر )")
        'المادة التاسعة والسبعين مكرر'
        >>> clean_heading("المادة الأولى: التعريفات")
        'المادة الأولى'
    """
    text = raw.split(_CURRENTLY, 1)[0].split(":", 1)[0]
    text = " ".join(_PARENS.sub(" ", text).split())
    return text if text.startswith(_ARTICLE_PREFIX) else f"{_ARTICLE_PREFIX} {text}"


def article_title(raw: str) -> str | None:
    """The article's own title after the colon, if any.

    Example:
        >>> article_title("المادة الثانية: تعريف الشركة")
        'تعريف الشركة'
    """
    if _CURRENTLY in raw or ":" not in raw:
        return None
    title = " ".join(raw.split(":", 1)[1].split())
    return title or None


def build_articles(law: PublishedLaw) -> list[Article]:
    """Turn a published law into articles with their text in force.

    Steps:
        1. Parse each block's number, heading and title.
        2. Parse its amendment notes and resolve the text in force.
        3. Create articles that exist only as an "added article" note inside
           another article (the portal sometimes has no block for them).

    Args:
        law: The law as fetched from the publisher.

    Returns:
        Articles in legal order (by number). Superseded articles keep their
        old number, so numbers are unique only among current articles; use
        `duplicate_current_numbers` to check.
    """
    articles = [_build_article(law, source) for source in law.sources]
    articles += list(_articles_added_in_notes(law, articles))
    return sorted(articles, key=lambda article: article.number)


def _build_article(law: PublishedLaw, source: ArticleSource) -> Article:
    number = parse_article_number(source.heading)
    body_note = _body_as_addition(source.body, number)
    notes = (source.body, *source.notes) if body_note else source.notes
    original_text = None if body_note else source.body
    amendments = tuple(parse_amendment(note) for note in notes)
    resolution = resolve(number, original_text or "", amendments)
    text, status = resolution.text, resolution.status
    if not text.strip():  # an addition note whose quoted text we could not read
        text, status = source.body, ArticleStatus.REVIEW_NEEDED
    return Article(
        law_id=law.law_id,
        law_title=law.title,
        number=number,
        heading=clean_heading(source.heading),
        text=text,
        status=status,
        title=article_title(source.heading),
        part=source.part,
        chapter=source.chapter,
        original_text=original_text,
        amendments=amendments,
    )


def _body_as_addition(body: str, number: ArticleNumber) -> bool:
    """True when the block's body is itself the note that added the article."""
    amendment = parse_amendment(body)
    return amendment.kind is AmendmentKind.ADD and amendment.target in (None, number)


def _articles_added_in_notes(law: PublishedLaw, articles: Sequence[Article]) -> Iterable[Article]:
    existing = {article.number for article in articles}
    for host in articles:
        for amendment in host.amendments:
            added = _added_article(law, host, amendment)
            if added is not None and added.number not in existing:
                existing.add(added.number)
                yield added


def _added_article(law: PublishedLaw, host: Article, amendment: Amendment) -> Article | None:
    """The article an ``ADD`` note creates, if it targets another article."""
    target, text, label = amendment.target, amendment.new_text, amendment.target_label
    if amendment.kind is not AmendmentKind.ADD or target is None or target == host.number:
        return None
    if not text or not label:
        return None
    return Article(
        law_id=law.law_id,
        law_title=law.title,
        number=target,
        heading=clean_heading(label),
        text=text,
        status=ArticleStatus.AMENDED,
        part=host.part,
        chapter=host.chapter,
        amendments=(amendment,),
    )


def duplicate_current_numbers(articles: Iterable[Article]) -> list[ArticleNumber]:
    """Numbers used by more than one *current* article (should be empty)."""
    counts = Counter(article.number for article in articles if article.is_current)
    return sorted(number for number, count in counts.items() if count > 1)
