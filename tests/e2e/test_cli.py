"""End-to-end: the ``masdar dataset`` command on the committed snapshots."""

import json
from pathlib import Path

import pytest

from masdar.entrypoints.cli import main


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshot_dir: Path) -> Path:
    monkeypatch.setenv("MASDAR_SNAPSHOT_DIR", str(snapshot_dir))
    monkeypatch.setenv("MASDAR_DATASET_DIR", str(tmp_path))
    return tmp_path


def test_builds_the_dataset_offline(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["dataset", "--offline"]) == 0
    stats = json.loads((env / "stats.json").read_text(encoding="utf-8"))
    assert [law["law_id"] for law in stats["laws"]] == ["labor-law", "pdpl", "companies-law"]
    corpus_lines = (env / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(corpus_lines) == 534  # current articles only
    history_lines = (env / "history.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(history_lines) == 42
    assert "labor-law" in capsys.readouterr().out


def test_unknown_law_fails_with_a_clear_message(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["dataset", "--offline", "--laws", "tax-law"]) == 1
    assert "Unknown law 'tax-law'" in capsys.readouterr().err
    assert not (env / "corpus.jsonl").exists()


@pytest.mark.usefixtures("env")
def test_invalid_settings_fail_fast(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("MASDAR_CRAWL_DELAY_SECONDS", "1")  # below robots.txt's 10 s
    assert main(["dataset", "--offline"]) == 1
    assert "crawl_delay_seconds" in capsys.readouterr().err


@pytest.mark.usefixtures("env")
def test_offline_and_refresh_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        main(["dataset", "--offline", "--refresh"])
