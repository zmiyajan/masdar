"""Every contract-checker rule is pinned to the text in force of its article.

The limits are read from the resolved corpus (committed snapshots, amendments
applied per ADR-0005), never from memory. If an amendment changes an article,
its heading, status, wording or number stops matching here and the build fails,
instead of the checker silently citing an outdated limit (ADR-0010).
"""

from pathlib import Path

import pytest

from masdar.config import Settings
from masdar.container import load_current_corpus
from masdar.domain.amendments import ArticleStatus
from masdar.domain.arabic import normalize_arabic
from masdar.domain.compliance import Rule
from masdar.domain.labor_rules import LABOR_RULES
from masdar.domain.models import Article
from masdar.domain.quantities import extract_quantities


@pytest.fixture(scope="module")
def articles(snapshot_dir: Path) -> dict[str, Article]:
    corpus = load_current_corpus(Settings(snapshot_dir=snapshot_dir))
    return {article.article_id: article for article in corpus.articles}


def _ids(rule: Rule) -> str:
    return rule.rule_id


@pytest.mark.parametrize("rule", LABOR_RULES, ids=_ids)
class TestRulePinnedToTextInForce:
    def test_article_is_current_with_the_recorded_heading_and_status(
        self, rule: Rule, articles: dict[str, Article]
    ) -> None:
        article = articles[rule.article_id]
        assert article.is_current
        assert (article.heading, article.status, article.law_title) == (
            rule.article_heading,
            rule.article_status,
            rule.law_title,
        )

    def test_source_phrase_is_in_the_text_in_force(
        self, rule: Rule, articles: dict[str, Article]
    ) -> None:
        # Normalized on both sides: the corpus mixes "يومًا" and "يوماً".
        assert normalize_arabic(rule.source_phrase) in normalize_arabic(
            articles[rule.article_id].text
        )

    def test_limit_is_stated_by_the_source_phrase(self, rule: Rule) -> None:
        stated = {(q.value, q.unit) for q in extract_quantities(rule.source_phrase)}
        assert (rule.limit.value, rule.limit.unit) in stated

    def test_limit_is_stated_in_the_text_in_force(
        self, rule: Rule, articles: dict[str, Article]
    ) -> None:
        stated = {(q.value, q.unit) for q in extract_quantities(articles[rule.article_id].text)}
        assert (rule.limit.value, rule.limit.unit) in stated


def test_amended_limits_differ_from_the_portal_wording(articles: dict[str, Article]) -> None:
    # The thesis in one test: the portal's main text states the old limits.
    probation = articles["labor-law:53"]
    maternity = articles["labor-law:151"]
    assert probation.original_text is not None
    assert maternity.original_text is not None
    assert "تسعين يوم" in normalize_arabic(probation.original_text)
    assert "مائه وثمانين" in normalize_arabic(probation.text)
    assert "اثني عشر" in normalize_arabic(maternity.text)
    assert "اثني عشر" not in normalize_arabic(maternity.original_text)


def test_a_rule_on_an_article_under_review_is_flagged() -> None:
    review = ArticleStatus.REVIEW_NEEDED
    assert [r.rule_id for r in LABOR_RULES if r.article_status is review] == ["overtime-rate-min"]
