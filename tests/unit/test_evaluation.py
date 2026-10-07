"""Tests for evaluation results and the `Evaluate` use case, on fakes."""

import pytest

from masdar.app.evaluate import Evaluate
from masdar.app.search import SearchService
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.evaluation import DEPTH, Scores, evaluate_query, summarize
from masdar.domain.gold import GoldQuery, QueryStyle
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber


def gold(
    query_id: str, relevant: dict[str, int], style: QueryStyle = QueryStyle.FORMAL
) -> GoldQuery:
    return GoldQuery(query_id, f"سؤال {query_id}", tuple(relevant.items()), "topic", style)


def chunk(article_id: str, index: int = 0) -> Chunk:
    law, _, number = article_id.partition(":")
    article = Article(law, "نظام", ArticleNumber(int(number)), f"المادة {number}", "نص")
    return Chunk(f"{article_id}#{index}", article, "نص", "نص")


class FakeGold:
    def __init__(self, queries: list[GoldQuery]) -> None:
        self.queries = queries

    @property
    def version(self) -> str:
        return "v9"

    def load(self) -> tuple[GoldQuery, ...]:
        return tuple(self.queries)


class FakeRetriever:
    """Returns canned chunk ids per question text."""

    def __init__(self, answers: dict[str, list[str]]) -> None:
        self.answers = answers

    @property
    def name(self) -> str:
        return "fake"

    def search(self, query: str, k: int) -> list[Hit]:
        chunk_ids = self.answers.get(query, [])[:k]
        return [
            Hit(chunk(chunk_id.split("#")[0], int(chunk_id.split("#")[1])), 1 / rank, rank, "fake")
            for rank, chunk_id in enumerate(chunk_ids, start=1)
        ]


class TestEvaluateQuery:
    def test_records_ranking_first_answer_and_scores(self) -> None:
        query = gold("q1", {"labor-law:2": 2, "labor-law:1": 1})
        result = evaluate_query(query, ["labor-law:1", "labor-law:9", "labor-law:2"])
        assert result.first_answer_rank == 3
        assert result.laws == ("labor-law",)
        assert result.scores.mrr_at_10 == 1.0  # the related article counts for MRR
        assert result.scores.recall_at_1 == 0.5
        assert result.scores.recall_at_3 == 1.0

    def test_only_the_top_depth_articles_are_judged(self) -> None:
        query = gold("q1", {"labor-law:99": 2})
        ranking = [f"labor-law:{n}" for n in range(1, DEPTH + 1)] + ["labor-law:99"]
        result = evaluate_query(query, ranking)
        assert len(result.ranking) == DEPTH
        assert result.first_answer_rank is None
        assert result.scores == Scores(0, 0, 0, 0, 0, 0)

    def test_laws_come_from_answering_articles_only(self) -> None:
        query = gold("q1", {"pdpl:1": 2, "labor-law:1": 1, "companies-law:3": 2})
        assert evaluate_query(query, []).laws == ("pdpl", "companies-law")


class TestSummarize:
    def test_means_overall_per_style_and_per_law(self) -> None:
        results = [
            evaluate_query(gold("q1", {"labor-law:1": 2}), ["labor-law:1"]),
            evaluate_query(gold("q2", {"pdpl:1": 2}, QueryStyle.DIALECT), ["x:1"]),
            evaluate_query(gold("q3", {"labor-law:2": 2}, QueryStyle.DIALECT), ["labor-law:2"]),
        ]
        report = summarize("fake", "v9", results)
        assert report.overall.recall_at_10 == pytest.approx(2 / 3)
        assert [(g.group, g.queries) for g in report.by_style] == [("formal", 1), ("dialect", 2)]
        assert report.by_style[1].scores.ndcg_at_10 == 0.5
        assert [(g.group, g.queries) for g in report.by_law] == [("labor-law", 2), ("pdpl", 1)]
        assert report.by_law[1].scores.ndcg_at_10 == 0.0
        assert [q.query_id for q in report.queries] == ["q1", "q2", "q3"]

    def test_rejects_an_empty_run(self) -> None:
        with pytest.raises(InvalidDomainObjectError):
            summarize("fake", "v9", [])


class TestEvaluate:
    def test_scores_articles_as_the_search_service_returns_them(self) -> None:
        queries = [
            gold("q1", {"labor-law:1": 2}),
            gold("q2", {"labor-law:2": 2, "labor-law:3": 1}, QueryStyle.PARAPHRASE),
        ]
        retriever = FakeRetriever(
            {
                # Two chunks of article 5 collapse into one article at rank 1.
                "سؤال q1": ["labor-law:5#0", "labor-law:5#1", "labor-law:1#0"],
                "سؤال q2": ["labor-law:3#0", "labor-law:2#0"],
            }
        )
        report = Evaluate(FakeGold(queries)).run(SearchService(retriever))
        assert (report.pipeline, report.gold_version) == ("fake", "v9")
        first, second = report.queries
        assert first.ranking == ("labor-law:5", "labor-law:1")
        assert first.first_answer_rank == 2
        assert second.first_answer_rank == 2
        assert second.scores.mrr_at_10 == 1.0
        assert report.overall.mrr_at_10 == pytest.approx(0.75)
