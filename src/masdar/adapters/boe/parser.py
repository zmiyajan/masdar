"""Parse a law page from laws.boe.gov.sa into a `PublishedLaw`.

Page structure (verified 2026-10, see ADR-0002):

- ``h1.system_title``: the law's title.
- ``h3`` outside article blocks: part (``الباب``) or chapter (``الفصل``) headings.
- ``div.article_item``: one article. Direct ``h3`` children hold an optional
  chapter heading and the article heading; ``div.HTMLContainer`` holds the
  body; each ``div.article_item_popup`` holds one amendment note.

This module only extracts text. Every legal decision (numbers, text in force)
is made in `masdar.domain.articles`.

The parse tree is never modified. An earlier version removed popups while
walking the page, which left stale elements in the walk and corrupted later
blocks; reading without mutation makes the walk order-independent.
"""

from bs4 import BeautifulSoup
from bs4.element import NavigableString, PreformattedString, Tag

from masdar.domain.articles import ArticleSource, PublishedLaw
from masdar.domain.errors import SourceFormatError

_STRUCTURE_PREFIXES = ("الباب", "الفصل")
_PART_PREFIX = "الباب"


def parse_law_html(html: str, *, law_id: str, source_url: str) -> PublishedLaw:
    """Extract the title and every article block from a law page.

    Args:
        html: The page HTML.
        law_id: Masdar's slug for the law.
        source_url: Where the page was fetched from (kept for provenance).

    Returns:
        The law with one `ArticleSource` per article block, in page order.

    Raises:
        SourceFormatError: If the page lacks a title or article blocks.
    """
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("h1.system_title")
    if title is None:
        raise SourceFormatError(f"{law_id}: no law title (h1.system_title) on the page")

    sources: list[ArticleSource] = []
    part: str | None = None
    chapter: str | None = None
    for element in soup.select("h3, div.article_item"):
        if element.name == "h3":
            if element.find_parent("div", class_="article_item") is None:
                part, chapter = _apply_structure(_text(element), part, chapter)
            continue
        source = _parse_article_block(element, part, chapter)
        part, chapter = source.part, source.chapter
        sources.append(source)

    if not sources:
        raise SourceFormatError(f"{law_id}: no article blocks (div.article_item) on the page")
    return PublishedLaw(law_id, _text(title), source_url, tuple(sources))


def _apply_structure(
    heading: str, part: str | None, chapter: str | None
) -> tuple[str | None, str | None]:
    """Track the part and chapter that apply to the following articles."""
    if heading.startswith(_PART_PREFIX):
        return heading, None
    if heading.startswith("الفصل"):
        return part, heading
    return part, chapter


def _parse_article_block(block: Tag, part: str | None, chapter: str | None) -> ArticleSource:
    heading: str | None = None
    for h3 in block.select(":scope > h3"):
        text = _text(h3)
        if text.startswith(_STRUCTURE_PREFIXES):
            part, chapter = _apply_structure(text, part, chapter)
        elif heading is None:
            heading = text
    if heading is None:
        raise SourceFormatError(f"Article block without a heading: {_text(block)[:80]!r}")

    containers = block.select("div.HTMLContainer")
    notes = tuple(_text(c) for c in containers if _in_popup(c))
    body = next((c for c in containers if not _in_popup(c)), None)
    if body is None:
        raise SourceFormatError(f"{heading}: no article body (div.HTMLContainer)")
    return ArticleSource(heading, _text(body), notes, part, chapter)


def _in_popup(element: Tag) -> bool:
    return element.find_parent("div", class_="article_item_popup") is not None


_BLOCK_TAGS = frozenset({"p", "div", "li", "tr", "h1", "h2", "h3", "h4"})
_SKIPPED_TAGS = frozenset({"script", "style"})


def _text(element: Tag) -> str:
    """Visible text with line breaks kept at <br> and block boundaries.

    Line breaks matter: they separate numbered paragraphs (``1-``, ``أ-``),
    which the chunker uses as split points.
    """
    pieces: list[str] = []
    _collect_text(element, pieces)
    lines = (" ".join(line.split()) for line in "".join(pieces).splitlines())
    return "\n".join(line for line in lines if line)


def _collect_text(node: Tag, pieces: list[str]) -> None:
    for child in node.children:
        if isinstance(child, NavigableString):
            if not isinstance(child, PreformattedString):  # skip comments, CDATA
                pieces.append(str(child))
        elif isinstance(child, Tag) and child.name not in _SKIPPED_TAGS:
            if child.name == "br":
                pieces.append("\n")
                continue
            _collect_text(child, pieces)
            if child.name in _BLOCK_TAGS:
                pieces.append("\n")
