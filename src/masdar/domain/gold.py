"""Gold questions: what a good search must find, judged by a person.

Each question maps to the articles that answer it, with graded relevance:
``2`` means the article answers the question, ``1`` means it is related and
useful. Graded judgments let nDCG reward putting the answering article first
(Järvelin & Kekäläinen, 2002).
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum

from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.models import Article

ANSWERS, RELATED = 2, 1
_VALID_GRADES = frozenset({ANSWERS, RELATED})


class QueryStyle(StrEnum):
    """How a question is worded; results are reported per style."""

    FORMAL = "formal"  # Modern Standard Arabic, close to legal wording
    DIALECT = "dialect"  # Saudi dialect, as people actually type
    PARAPHRASE = "paraphrase"  # everyday terms the law does not use ("الأوفرتايم")


@dataclass(frozen=True, slots=True)
class GoldQuery:
    """One gold question.

    Attributes:
        query_id: Stable id, e.g. ``"q001"``.
        text: The question as a user would type it.
        relevant: ``(article_id, grade)`` pairs, grade 2 = answers, 1 = related.
        topic: Short topic label, e.g. ``"probation"``.
        style: How the question is worded.
    """

    query_id: str
    text: str
    relevant: tuple[tuple[str, int], ...]
    topic: str
    style: QueryStyle

    def __post_init__(self) -> None:
        """A question without an answering article cannot be scored."""
        if not self.query_id.strip() or not self.text.strip():
            raise InvalidDomainObjectError("GoldQuery needs an id and a text")
        grades = [grade for _, grade in self.relevant]
        if not grades or any(grade not in _VALID_GRADES for grade in grades):
            raise InvalidDomainObjectError(f"{self.query_id}: grades must be 1 or 2, got {grades}")
        if ANSWERS not in grades:
            raise InvalidDomainObjectError(f"{self.query_id}: needs at least one answering article")

    @property
    def grades(self) -> Mapping[str, int]:
        """Relevance grade per article id."""
        return dict(self.relevant)


def unresolved_references(queries: Iterable[GoldQuery], articles: Iterable[Article]) -> list[str]:
    """Gold references that do not point at a current article, as readable messages.

    A gold set that cites a repealed or unknown article would silently score
    every system as wrong for that question, so the build refuses it.
    """
    current = {article.article_id for article in articles if article.is_current}
    return [
        f"{query.query_id} -> {article_id}"
        for query in queries
        for article_id, _ in query.relevant
        if article_id not in current
    ]
