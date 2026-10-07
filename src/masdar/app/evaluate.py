"""Use case: measure a search pipeline against the gold questions."""

from masdar.app.search import SearchService
from masdar.domain.evaluation import DEPTH, EvaluationReport, evaluate_query, summarize
from masdar.ports.gold_source import GoldSource


class Evaluate:
    """Run every gold question through a `SearchService` and score the articles.

    The pipeline is called exactly as the API calls it (same service, same
    article collapsing), so the reported numbers describe what users get.
    """

    def __init__(self, gold: GoldSource) -> None:
        """Create the use case.

        Args:
            gold: Source of the gold questions and their judgments.
        """
        self._gold = gold

    def run(self, service: SearchService) -> EvaluationReport:
        """Evaluate ``service`` on the whole gold set.

        Raises:
            InvalidDomainObjectError: If the gold set is empty.
        """
        results = [
            evaluate_query(
                query,
                [result.article.article_id for result in service.search(query.text, k=DEPTH)],
            )
            for query in self._gold.load()
        ]
        return summarize(service.name, self._gold.version, results)
