"""Tests for the CheckContract use case, with a fake retriever."""

import pytest

from masdar.app.check_contract import DEFAULT_MAX_CHARS, CheckContract
from masdar.app.search import SearchService
from masdar.domain.compliance import FindingKind
from masdar.domain.errors import InvalidDomainObjectError
from masdar.domain.labor_rules import LABOR_RULES
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber
from masdar.domain.search import MAX_QUERY_CHARS

ARTICLES = (
    Article("labor-law", "نظام العمل", ArticleNumber(53), "المادة الثالثة والخمسون", "التجربة"),
    Article("labor-law", "نظام العمل", ArticleNumber(109), "المادة التاسعة بعد المائة", "إجازة"),
    Article("pdpl", "نظام حماية البيانات الشخصية", ArticleNumber(4), "المادة الرابعة", "حقوق"),
)


class FakeRetriever:
    """Returns every article in a fixed order and records each query."""

    name = "fake"

    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, k: int) -> list[Hit]:
        self.queries.append(query)
        chunks = [Chunk(f"{a.article_id}#0", a, a.text, a.text) for a in ARTICLES]
        return [Hit(c, 1.0 / rank, rank, self.name) for rank, c in enumerate(chunks[:k], 1)]


CONTRACT = (
    "عقد عمل غير محدد المدة\n"
    "1- يخضع الموظف لفترة تجربة مدتها 200 يوم.\n"
    "2- تلتزم الشركة بحماية البيانات الشخصية للموظف.\n"
    "3- الإجازة السنوية 30 يوماً."
)


@pytest.fixture
def retriever() -> FakeRetriever:
    return FakeRetriever()


@pytest.fixture
def checker(retriever: FakeRetriever) -> CheckContract:
    return CheckContract(SearchService(retriever), LABOR_RULES, related_k=2)


def test_every_clause_gets_findings_and_related_articles(
    checker: CheckContract, retriever: FakeRetriever
) -> None:
    report = checker.run(CONTRACT)
    assert [r.clause.index for r in report.clauses] == [1, 2, 3, 4]
    assert [[f.rule_id for f in r.findings] for r in report.clauses] == [
        [],
        ["probation-max"],
        [],
        ["annual-leave-min"],
    ]
    assert report.counts == {
        FindingKind.VIOLATION: 1,
        FindingKind.COMPLIANT: 1,
        FindingKind.REVIEW_NEEDED: 0,
    }
    assert all(len(r.related) == 2 for r in report.clauses)
    assert retriever.queries[1] == "1- يخضع الموظف لفترة تجربة مدتها 200 يوم."


def test_laws_filter_restricts_rules_and_related_articles(checker: CheckContract) -> None:
    report = checker.run(CONTRACT, laws=["pdpl"])
    assert report.counts[FindingKind.VIOLATION] == 0
    assert {a.article.law_id for r in report.clauses for a in r.related} == {"pdpl"}


def test_long_clauses_are_cut_for_retrieval(
    checker: CheckContract, retriever: FakeRetriever
) -> None:
    checker.run("بند " * 300)
    assert len(retriever.queries) == 1
    assert len(retriever.queries[0]) <= MAX_QUERY_CHARS


@pytest.mark.parametrize("text", ["", "   \n  "])
def test_rejects_an_empty_document(checker: CheckContract, text: str) -> None:
    with pytest.raises(InvalidDomainObjectError):
        checker.run(text)


def test_rejects_an_oversized_document(retriever: FakeRetriever) -> None:
    checker = CheckContract(SearchService(retriever), LABOR_RULES, max_chars=10)
    with pytest.raises(InvalidDomainObjectError):
        checker.run("فترة التجربة 90 يوماً")
    assert DEFAULT_MAX_CHARS > MAX_QUERY_CHARS


@pytest.mark.parametrize(("related_k", "max_chars"), [(0, 100), (3, 0)])
def test_rejects_bad_settings(retriever: FakeRetriever, related_k: int, max_chars: int) -> None:
    with pytest.raises(InvalidDomainObjectError):
        CheckContract(
            SearchService(retriever), LABOR_RULES, related_k=related_k, max_chars=max_chars
        )
