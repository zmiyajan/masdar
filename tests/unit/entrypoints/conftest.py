"""Fixtures for the entrypoint tests: a real SearchService over a fake retriever."""

import pytest

from entrypoints.entrypoint_fakes import REPO_ROOT, FakeRetriever
from masdar.app.search import SearchService
from masdar.config import Settings


@pytest.fixture
def retriever() -> FakeRetriever:
    return FakeRetriever()


@pytest.fixture
def service(retriever: FakeRetriever) -> SearchService:
    return SearchService(retriever)


@pytest.fixture
def settings() -> Settings:
    return Settings(dataset_dir=REPO_ROOT / "data" / "dataset")
