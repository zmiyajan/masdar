"""Tests for domain model invariants."""

import dataclasses
import math

import pytest

from masdar.domain.amendments import ArticleStatus
from masdar.domain.errors import InvalidDomainObjectError, MasdarError
from masdar.domain.models import Article, Chunk, Hit
from masdar.domain.ordinals import ArticleNumber


def make_article(**overrides: object) -> Article:
    fields: dict[str, object] = {
        "law_id": "labor-law",
        "law_title": "نظام العمل",
        "number": ArticleNumber(1),
        "heading": "المادة الأولى",
        "text": "يسمى هذا النظام نظام العمل.",
    }
    fields.update(overrides)
    return Article(**fields)  # type: ignore[arg-type]


def make_chunk(**overrides: object) -> Chunk:
    fields: dict[str, object] = {
        "chunk_id": "labor-law:1:0",
        "article": make_article(),
        "text": "يسمى هذا النظام نظام العمل.",
        "normalized_text": "يسمي هذا النظام نظام العمل.",
    }
    fields.update(overrides)
    return Chunk(**fields)  # type: ignore[arg-type]


def make_hit(**overrides: object) -> Hit:
    fields: dict[str, object] = {
        "chunk": make_chunk(),
        "score": 1.0,
        "rank": 1,
        "retriever": "bm25",
    }
    fields.update(overrides)
    return Hit(**fields)  # type: ignore[arg-type]


class TestArticle:
    def test_citation_combines_law_title_and_heading(self) -> None:
        assert make_article().citation == "نظام العمل — المادة الأولى"

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"law_id": "  "}, id="blank-law-id"),
            pytest.param({"law_title": ""}, id="blank-law-title"),
            pytest.param({"heading": " "}, id="blank-heading"),
            pytest.param({"text": "\n"}, id="blank-text"),
        ],
    )
    def test_rejects_invalid_values(self, overrides: dict[str, object]) -> None:
        with pytest.raises(InvalidDomainObjectError):
            make_article(**overrides)

    def test_article_id_uses_number_slug(self) -> None:
        assert make_article(number=ArticleNumber(79, bis=True)).article_id == "labor-law:79-bis"

    @pytest.mark.parametrize(
        ("status", "current"),
        [
            (ArticleStatus.IN_FORCE, True),
            (ArticleStatus.AMENDED, True),
            (ArticleStatus.REVIEW_NEEDED, True),
            (ArticleStatus.REPEALED, False),
            (ArticleStatus.SUPERSEDED, False),
        ],
    )
    def test_only_in_force_like_statuses_are_current(
        self, status: ArticleStatus, current: bool
    ) -> None:
        assert make_article(status=status).is_current is current

    def test_is_immutable(self) -> None:
        article = make_article()
        with pytest.raises(dataclasses.FrozenInstanceError):
            article.number = ArticleNumber(2)  # type: ignore[misc]


class TestChunk:
    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"chunk_id": ""}, id="blank-id"),
            pytest.param({"text": ""}, id="nothing-to-show"),
            pytest.param({"normalized_text": " "}, id="nothing-to-search"),
        ],
    )
    def test_rejects_invalid_values(self, overrides: dict[str, object]) -> None:
        with pytest.raises(InvalidDomainObjectError):
            make_chunk(**overrides)

    def test_equal_chunks_hash_equal_so_they_deduplicate(self) -> None:
        assert len({make_chunk(), make_chunk()}) == 1


class TestHit:
    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"rank": 0}, id="rank-zero"),
            pytest.param({"rank": True}, id="bool-rank"),
            pytest.param({"score": math.nan}, id="nan-score"),
            pytest.param({"score": math.inf}, id="infinite-score"),
            pytest.param({"retriever": ""}, id="blank-retriever"),
        ],
    )
    def test_rejects_invalid_values(self, overrides: dict[str, object]) -> None:
        with pytest.raises(InvalidDomainObjectError):
            make_hit(**overrides)

    def test_is_hashable(self) -> None:
        assert hash(make_hit()) == hash(make_hit())


def test_domain_errors_share_one_base_class() -> None:
    assert issubclass(InvalidDomainObjectError, MasdarError)
    assert issubclass(InvalidDomainObjectError, ValueError)
