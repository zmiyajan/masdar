"""Evaluation results: how well one pipeline ranks the gold articles.

Scoring happens at the article level, the unit users cite and the gold set
judges: a pipeline's chunk hits are collapsed to articles first (see
`masdar.domain.search.collapse_to_articles`), then compared with the gold
grades. Scores are macro-averaged, so every question weighs the same.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean
from typing import Self

from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.gold import ANSWERS, GoldQuery, QueryStyle
from masdar.domain.metrics import first_rank, ndcg_at_k, recall_at_k, reciprocal_rank_at_k

DEPTH = 10
"""How many articles are judged per question; MRR and nDCG are cut off here."""


@dataclass(frozen=True, slots=True)
class Scores:
    """Ranking quality for one question, or the mean over several.

    Attributes:
        recall_at_1: Share of relevant articles in the top 1.
        recall_at_3: ... in the top 3.
        recall_at_5: ... in the top 5.
        recall_at_10: ... in the top 10.
        mrr_at_10: Reciprocal rank of the first relevant article (0 if below 10).
        ndcg_at_10: Graded nDCG at 10.
    """

    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    recall_at_10: float
    mrr_at_10: float
    ndcg_at_10: float

    @classmethod
    def of(cls, ranking: Sequence[str], query: GoldQuery) -> Self:
        """Score one ranking of article ids against ``query``'s judgments."""
        grades = query.grades
        return cls(
            recall_at_1=recall_at_k(ranking, grades, 1),
            recall_at_3=recall_at_k(ranking, grades, 3),
            recall_at_5=recall_at_k(ranking, grades, 5),
            recall_at_10=recall_at_k(ranking, grades, DEPTH),
            mrr_at_10=reciprocal_rank_at_k(ranking, grades, DEPTH),
            ndcg_at_10=ndcg_at_k(ranking, grades, DEPTH),
        )

    @classmethod
    def mean(cls, scores: Sequence[Self]) -> Self:
        """Macro-average: each question counts once.

        Raises:
            InvalidDomainObjectError: If ``scores`` is empty.
        """
        if not scores:
            raise InvalidDomainObjectError("Cannot average zero scores")
        return cls(
            recall_at_1=fmean(s.recall_at_1 for s in scores),
            recall_at_3=fmean(s.recall_at_3 for s in scores),
            recall_at_5=fmean(s.recall_at_5 for s in scores),
            recall_at_10=fmean(s.recall_at_10 for s in scores),
            mrr_at_10=fmean(s.mrr_at_10 for s in scores),
            ndcg_at_10=fmean(s.ndcg_at_10 for s in scores),
        )


@dataclass(frozen=True, slots=True)
class QueryEvaluation:
    """How a pipeline did on one gold question.

    Attributes:
        query_id: Gold question id.
        style: How the question is worded.
        laws: Laws of the articles that answer it.
        ranking: Article ids the pipeline returned, best first (at most `DEPTH`).
        first_answer_rank: Rank of the first article graded "answers", or
            ``None`` if none was returned. Stricter than MRR, which also
            accepts a "related" article.
        scores: The question's metrics.
    """

    query_id: str
    style: QueryStyle
    laws: tuple[str, ...]
    ranking: tuple[str, ...]
    first_answer_rank: int | None
    scores: Scores


@dataclass(frozen=True, slots=True)
class GroupScores:
    """Mean scores over a subset of questions (one style, or one law).

    Attributes:
        group: The style or law id.
        queries: Number of questions in the group.
        scores: Their mean scores.
    """

    group: str
    queries: int
    scores: Scores


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Everything one evaluation run produced for one pipeline.

    Attributes:
        pipeline: Pipeline name, e.g. ``"bm25"``.
        gold_version: Version of the gold set, e.g. ``"v1"``.
        overall: Mean over all questions.
        by_style: Mean per `QueryStyle`, in enum order.
        by_law: Mean per law, in order of first appearance in the gold set.
        queries: Per-question detail, in gold order.
    """

    pipeline: str
    gold_version: str
    overall: Scores
    by_style: tuple[GroupScores, ...]
    by_law: tuple[GroupScores, ...]
    queries: tuple[QueryEvaluation, ...]


def evaluate_query(query: GoldQuery, ranking: Sequence[str]) -> QueryEvaluation:
    """Score one question given the article ids a pipeline ranked for it."""
    top = tuple(ranking[:DEPTH])
    answering = [article for article, grade in query.relevant if grade == ANSWERS]
    return QueryEvaluation(
        query_id=query.query_id,
        style=query.style,
        laws=tuple(dict.fromkeys(_law_of(article) for article in answering)),
        ranking=top,
        first_answer_rank=first_rank(top, query.grades, ANSWERS),
        scores=Scores.of(top, query),
    )


def summarize(
    pipeline: str, gold_version: str, results: Sequence[QueryEvaluation]
) -> EvaluationReport:
    """Aggregate per-question results into overall, per-style and per-law means.

    A question whose answering articles span several laws counts in each.

    Raises:
        InvalidDomainObjectError: If ``results`` is empty.
    """
    by_law: dict[str, list[Scores]] = {}
    for result in results:
        for law in result.laws:
            by_law.setdefault(law, []).append(result.scores)
    styles = [
        (style.value, [r.scores for r in results if r.style is style]) for style in QueryStyle
    ]
    return EvaluationReport(
        pipeline=pipeline,
        gold_version=gold_version,
        overall=Scores.mean([result.scores for result in results]),
        by_style=tuple(_group(name, scores) for name, scores in styles if scores),
        by_law=tuple(_group(name, scores) for name, scores in by_law.items()),
        queries=tuple(results),
    )


def _group(name: str, scores: Sequence[Scores]) -> GroupScores:
    return GroupScores(name, len(scores), Scores.mean(scores))


def _law_of(article_id: str) -> str:
    # Article ids are "<law_id>:<number slug>" (see `Article.article_id`).
    return article_id.partition(":")[0]
