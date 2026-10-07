"""The searchable corpus every retriever, the API and the evaluation share."""

from pathlib import Path

from masdar.config import Settings
from masdar.container import load_current_corpus


def test_corpus_holds_current_law_only(snapshot_dir: Path) -> None:
    corpus = load_current_corpus(Settings(snapshot_dir=snapshot_dir))
    assert len(corpus.articles) == 534
    assert all(article.is_current for article in corpus.articles)
    assert len(corpus.chunks) == 540
    assert {chunk.article.article_id for chunk in corpus.chunks} == {
        article.article_id for article in corpus.articles
    }
