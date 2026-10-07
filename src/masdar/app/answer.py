"""Use case: answer a question by quoting the law, or say it was not found.

The flow (ADR-0009):

1. Search, through the same `SearchService` users get, for the top articles.
2. Split each article into sentences (`split_sentences`, verbatim).
3. Score every (question, sentence) pair with the `PairScorer`, the same
   cross-encoder that reranks search results, so no extra model is loaded.
4. Rank sentences by their own score plus their article's reranker score,
   and refuse below a calibrated threshold.

Nothing is generated or paraphrased, so an answer can be wrong only by quoting
the wrong sentence, never by saying something the law does not say.
"""

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from masdar.app.search import SearchService
from masdar.domain.answer import (
    Answer,
    AnswerQualityReport,
    AnswerStatus,
    Evidence,
    OutOfScopeQuestion,
    split_sentences,
    summarize_answers,
)
from masdar.domain.chunking import context_line
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.gold import GoldQuery
from masdar.domain.search import ArticleResult, validate_query
from masdar.ports.pair_scorer import PairScorer


@dataclass(frozen=True, slots=True)
class _Candidate:
    result: ArticleResult
    sentence: str
    position: int
    score: float


class AnswerService:
    """Extractive question answering over the retrieved articles.

    The answer score of a sentence is the cross-encoder logit for
    ``(question, article location + sentence)`` plus the reranker logit of its
    article. The article term carries the evidence that the *article* is the
    right one (the reranker read all of it); the sentence term picks the line
    inside it. Measured against the sentence score alone, the sum lifted
    held-out attribution accuracy from 0.77 to 0.83 (ADR-0009).

    The search service must therefore rerank with the same cross-encoder as
    ``scorer``: the threshold is calibrated on the sum of two logits of that
    model, and a cosine score from a dense-only pipeline would be meaningless
    here.
    """

    def __init__(
        self,
        search: SearchService,
        scorer: PairScorer,
        *,
        threshold: float,
        articles: int = 3,
        max_sentences: int = 2,
    ) -> None:
        """Create the service.

        Args:
            search: The served search pipeline, with a cross-encoder reranker.
            scorer: Scores (question, passage) pairs; the reranker's own scorer.
            threshold: Minimum answer score; below it the answer is ``NOT_FOUND``.
            articles: How many top articles to read sentences from.
            max_sentences: Most sentences quoted, all from the best article.

        Raises:
            InvalidDomainObjectError: If ``articles`` or ``max_sentences`` is below 1.
        """
        if articles < 1 or max_sentences < 1:
            raise InvalidDomainObjectError(
                f"articles and max_sentences must be >= 1, got {articles}, {max_sentences}"
            )
        self._search = search
        self._scorer = scorer
        self._threshold = threshold
        self._articles = articles
        self._max_sentences = max_sentences

    @property
    def name(self) -> str:
        """E.g. ``"extractive(dense+rerank)"``."""
        return f"extractive({self._search.name})"

    def answer(
        self, question: str, laws: Collection[str] | None = None, related: int | None = None
    ) -> Answer:
        """Answer ``question`` with verbatim sentences of the law, or refuse.

        Args:
            question: The user's question.
            laws: Restrict the search to these law ids.
            related: Articles to return for reading around the answer;
                defaults to the ``articles`` read. Only the top ``articles``
                are quoted from, so this never changes the answer itself.
                When the quoted article ranks below ``related``, the list is
                extended to include it, so a quote always has its article.

        Returns:
            ``ANSWERED`` with up to ``max_sentences`` quotes from the best
            article, or ``NOT_FOUND``; ``related`` holds the articles read in
            both cases.

        Raises:
            InvalidDomainObjectError: If the question is empty or too long, or
                the scorer returns the wrong number of scores.
        """
        text = validate_query(question)
        shown = related or self._articles
        results = tuple(self._search.search(text, k=max(self._articles, shown), laws=laws))
        ranked = self._rank(text, results[: self._articles])
        if not ranked or ranked[0].score < self._threshold:
            return Answer(text, AnswerStatus.NOT_FOUND, (), results[:shown])
        best_article = ranked[0].result.article.article_id
        # Runners-up from other articles were almost never relevant in the
        # measurement, so extra quotes come only from the best article.
        chosen = [
            candidate
            for candidate in ranked
            if candidate.result.article.article_id == best_article
            and candidate.score >= self._threshold
        ][: self._max_sentences]
        evidence = tuple(
            Evidence(candidate.result.article, candidate.sentence, candidate.score)
            for candidate in chosen
        )
        # The quoted article must be among the related ones the caller shows.
        quoted = next(i for i, r in enumerate(results) if r.article.article_id == best_article)
        return Answer(text, AnswerStatus.ANSWERED, evidence, results[: max(shown, quoted + 1)])

    def _rank(self, question: str, related: Sequence[ArticleResult]) -> list[_Candidate]:
        """Every sentence of ``related``, best first.

        One scorer call for all sentences: a single padded batch is much faster
        than one forward pass per article.
        """
        units = [
            (result, sentence, position)
            for result in related
            for position, sentence in enumerate(split_sentences(result.article.text))
        ]
        if not units:
            return []
        scores = self._scorer.score(
            [
                (question, f"{context_line(result.article)}\n{sentence}")
                for result, sentence, _ in units
            ]
        )
        if len(scores) != len(units):
            raise InvalidDomainObjectError(f"Scorer returned {len(scores)} scores for {len(units)}")
        candidates = [
            _Candidate(result, sentence, position, score + result.score)
            for (result, sentence, position), score in zip(units, scores, strict=True)
        ]
        # Ties fall back to article rank, then reading order: reproducible output.
        return sorted(candidates, key=lambda c: (-c.score, c.result.rank, c.position))


def measure_answers(
    service: AnswerService,
    gold: Sequence[GoldQuery],
    out_of_scope: Sequence[OutOfScopeQuestion],
) -> AnswerQualityReport:
    """Run ``service`` over answerable and unanswerable questions and score it.

    Args:
        service: The answer service, exactly as served.
        gold: Questions the corpus answers, with judged articles.
        out_of_scope: Questions it does not answer; refusing them is correct.

    Raises:
        InvalidDomainObjectError: If ``gold`` is empty.
    """
    answered = [(query, service.answer(query.text)) for query in gold]
    refused = [service.answer(question.text) for question in out_of_scope]
    return summarize_answers(service.name, answered, refused)
