"""Tests for gold questions, the gold file adapter, and article-level search."""

import json
from collections.abc import Sequence
from pathlib import Path

import pytest

from masdar.adapters.beir_writer import to_beir_query, to_qrels_tsv
from masdar.adapters.gold_jsonl import JsonlGoldSource
from masdar.app.search import SearchService
from masdar.domain.amendments import ArticleStatus
from masdar.domain.errors import InvalidDomainObjectError, SourceFormatError
from masdar.domain.gold import GoldQuery, QueryStyle, unresolved_references
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber
from masdar.domain.search import MAX_QUERY_CHARS, collapse_to_articles, validate_query


def article(number: int, status: ArticleStatus = ArticleStatus.IN_FORCE) -> Article:
    return Article(
        "labor-law", "نظام العمل", ArticleNumber(number), f"المادة {number}", "نص", status
    )


def chunk(number: int, index: int = 0) -> Chunk:
    return Chunk(f"labor-law:{number}#{index}", article(number), "نص", "نص")


def hit(number: int, rank: int, index: int = 0) -> Hit:
    return Hit(chunk(number, index), score=1.0 / rank, rank=rank, retriever="fake")


class TestGoldQuery:
    def test_grades(self) -> None:
        query = GoldQuery("q1", "سؤال", (("a:1", 2), ("a:2", 1)), "t", QueryStyle.DIALECT)
        assert query.grades == {"a:1": 2, "a:2": 1}

    @pytest.mark.parametrize(
        "relevant",
        [
            pytest.param((), id="no-judgments"),
            pytest.param((("a:1", 3),), id="bad-grade"),
            pytest.param((("a:1", 1),), id="no-answering-article"),
        ],
    )
    def test_rejects_unusable_judgments(self, relevant: tuple[tuple[str, int], ...]) -> None:
        with pytest.raises(InvalidDomainObjectError):
            GoldQuery("q1", "سؤال", relevant, "t", QueryStyle.FORMAL)

    def test_references_must_point_at_current_articles(self) -> None:
        query = GoldQuery(
            "q1", "سؤال", (("labor-law:1", 2), ("labor-law:2", 1)), "t", QueryStyle.FORMAL
        )
        problems = unresolved_references([query], [article(1), article(2, ArticleStatus.REPEALED)])
        assert problems == ["q1 -> labor-law:2"]


class TestJsonlGoldSource:
    def write(self, tmp_path: Path, *lines: str) -> Path:
        path = tmp_path / "queries.v7.jsonl"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def test_loads_questions_and_version(self, tmp_path: Path) -> None:
        record = {
            "_id": "q1",
            "text": "سؤال",
            "relevant": {"a:1": 2},
            "topic": "t",
            "style": "paraphrase",
        }
        source = JsonlGoldSource(self.write(tmp_path, json.dumps(record, ensure_ascii=False), ""))
        [query] = source.load()
        assert (query.query_id, query.style, source.version) == ("q1", QueryStyle.PARAPHRASE, "v7")

    @pytest.mark.parametrize(
        ("line", "message"),
        [
            pytest.param("{not json", "invalid JSON", id="bad-json"),
            pytest.param('{"_id": "q1"}', "invalid gold record", id="missing-field"),
            pytest.param(
                '{"_id": "q1", "text": "س", "relevant": {"a:1": 1}, "topic": "t", '
                '"style": "formal"}',
                "answering article",
                id="domain-rule",
            ),
            pytest.param(
                '{"_id": "q1", "text": "س", "relevant": {"a:1": 2}, "topic": "t", "style": "poem"}',
                "invalid gold record",
                id="unknown-style",
            ),
        ],
    )
    def test_rejects_bad_lines_with_their_location(
        self, tmp_path: Path, line: str, message: str
    ) -> None:
        source = JsonlGoldSource(self.write(tmp_path, line))
        with pytest.raises(SourceFormatError, match=rf"queries\.v7\.jsonl:1: .*{message}"):
            source.load()

    def test_rejects_duplicate_ids(self, tmp_path: Path) -> None:
        line = '{"_id": "q1", "text": "س", "relevant": {"a:1": 2}, "topic": "t", "style": "formal"}'
        with pytest.raises(SourceFormatError, match="duplicate id q1"):
            JsonlGoldSource(self.write(tmp_path, line, line)).load()

    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(SourceFormatError, match="not found"):
            JsonlGoldSource(tmp_path / "queries.jsonl").load()
        assert JsonlGoldSource(tmp_path / "queries.jsonl").version == "unversioned"


def test_beir_query_and_qrels_format() -> None:
    query = GoldQuery("q1", "سؤال", (("a:1", 2), ("a:2", 1)), "leave", QueryStyle.FORMAL)
    assert to_beir_query(query) == {
        "_id": "q1",
        "text": "سؤال",
        "metadata": {"topic": "leave", "style": "formal"},
    }
    assert to_qrels_tsv([query]) == "query-id\tcorpus-id\tscore\nq1\ta:1\t2\nq1\ta:2\t1\n"


class TestCollapseToArticles:
    def test_keeps_the_best_chunk_per_article_and_reranks(self) -> None:
        results = collapse_to_articles([hit(5, 1), hit(5, 2, index=1), hit(9, 3)], k=10)
        assert [(r.article.number.value, r.rank, r.matched.chunk_id) for r in results] == [
            (5, 1, "labor-law:5#0"),
            (9, 2, "labor-law:9#0"),
        ]

    def test_respects_k(self) -> None:
        assert len(collapse_to_articles([hit(n, n) for n in range(1, 6)], k=2)) == 2


@pytest.mark.parametrize("bad", ["", "   ", "س" * (MAX_QUERY_CHARS + 1)])
def test_validate_query_rejects_empty_and_oversized(bad: str) -> None:
    with pytest.raises(InvalidDomainObjectError):
        validate_query(bad)


class FakeRetriever:
    name = "fake"

    def __init__(self, hits: list[Hit]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, k: int) -> list[Hit]:
        self.calls.append((query, k))
        return self.hits[:k]


class ReverseReranker:
    name = "reverse"

    def rerank(self, query: str, hits: Sequence[Hit], k: int) -> list[Hit]:  # noqa: ARG002
        ordered = list(reversed(hits))[:k]
        return [Hit(h.chunk, h.score, i, self.name) for i, h in enumerate(ordered, start=1)]


class TestSearchService:
    def test_trims_query_and_asks_for_candidates(self) -> None:
        retriever = FakeRetriever([hit(1, 1)])
        SearchService(retriever, candidates=30).search("  سؤال  ", k=5)
        assert retriever.calls == [("سؤال", 30)]

    def test_reranker_reorders_candidates(self) -> None:
        service = SearchService(FakeRetriever([hit(1, 1), hit(2, 2)]), ReverseReranker())
        assert [r.article.number.value for r in service.search("سؤال")] == [2, 1]
        assert service.name == "fake+reverse"

    def test_law_filter_reaches_past_other_laws(self) -> None:
        # The only PDPL hit ranks below more labor-law hits than one batch holds.
        labor = [hit(n, n) for n in range(1, 8)]
        pdpl_chunk = Chunk(
            "pdpl:3#0",
            Article("pdpl", "نظام حماية البيانات الشخصية", ArticleNumber(3), "م", "نص"),
            "نص",
            "نص",
        )
        retriever = FakeRetriever([*labor, Hit(pdpl_chunk, 0.01, 8, "fake")])
        results = SearchService(retriever, candidates=2).search("سؤال", laws={"pdpl"})
        assert [r.article.article_id for r in results] == ["pdpl:3"]
        assert [k for _, k in retriever.calls] == [2, 4, 8, 16]

    def test_law_filter(self) -> None:
        service = SearchService(FakeRetriever([hit(1, 1)]))
        assert service.search("سؤال", laws={"pdpl"}) == []
        assert service.name == "fake"
