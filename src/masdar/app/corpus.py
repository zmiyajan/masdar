"""Use case: load the current law as articles and indexable chunks."""

from collections.abc import Sequence
from dataclasses import dataclass

from masdar.domain.arabic import ArabicNormalizer
from masdar.domain.articles import build_articles
from masdar.domain.chunking import ChunkingOptions, chunk_article
from masdar.domain.models import Article, Chunk
from masdar.ports.law_source import LawSource


@dataclass(frozen=True, slots=True)
class Corpus:
    """Current articles and the chunks retrievers index."""

    articles: tuple[Article, ...]
    chunks: tuple[Chunk, ...]


def load_corpus(
    source: LawSource,
    normalizer: ArabicNormalizer,
    chunking: ChunkingOptions,
    law_ids: Sequence[str] | None = None,
) -> Corpus:
    """Build the searchable corpus: current articles only, chunked.

    Repealed and superseded articles are excluded: a search engine for
    compliance must never answer with law that is no longer in force.
    """
    articles = [
        article
        for law_id in law_ids or source.law_ids()
        for article in build_articles(source.load(law_id))
        if article.is_current
    ]
    chunks = [
        chunk for article in articles for chunk in chunk_article(article, normalizer, chunking)
    ]
    return Corpus(tuple(articles), tuple(chunks))
