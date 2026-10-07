"""The pipeline registry in the composition root."""

import importlib.util
from pathlib import Path

import pytest

from masdar.config import Settings
from masdar.container import PIPELINES, default_search_service, search_service
from masdar.domain.errors import MasdarError


def test_default_service_follows_the_setting(snapshot_dir: Path) -> None:
    settings = Settings(snapshot_dir=snapshot_dir, pipeline="bm25")
    assert default_search_service(settings).name == "bm25"


def test_unknown_pipeline_names_the_valid_ones(snapshot_dir: Path) -> None:
    with pytest.raises(MasdarError, match=r"unknown pipeline 'nope'.*'dense\+rerank'"):
        search_service(Settings(snapshot_dir=snapshot_dir), "nope")


def test_semantic_pipeline_without_ml_extra_explains_the_fix(
    snapshot_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(importlib.util, "find_spec", lambda _name: None)
    with pytest.raises(MasdarError, match="uv sync --extra ml"):
        search_service(Settings(snapshot_dir=snapshot_dir), "dense")


@pytest.mark.slow
def test_semantic_names_are_the_pipeline_names(snapshot_dir: Path, tmp_path: Path) -> None:
    # Results files are named after SearchService.name; a mismatch would file
    # one pipeline's scores under another's name.
    settings = Settings(snapshot_dir=snapshot_dir, index_dir=tmp_path)
    semantic = [name for name in PIPELINES if not name.startswith("bm25")]
    assert [search_service(settings, name).name for name in semantic] == semantic
