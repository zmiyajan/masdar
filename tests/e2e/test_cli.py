"""End-to-end: the ``masdar dataset`` command on the committed snapshots."""

import json
from pathlib import Path

import pytest

from masdar.entrypoints.cli import main


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, snapshot_dir: Path) -> Path:
    monkeypatch.setenv("MASDAR_SNAPSHOT_DIR", str(snapshot_dir))
    monkeypatch.setenv("MASDAR_DATASET_DIR", str(tmp_path))
    # The lexical pipeline: deterministic, model-free, and fast enough for e2e.
    monkeypatch.setenv("MASDAR_PIPELINE", "bm25")
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


@pytest.fixture
def eval_env(env: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Settings for the search commands; results go to a fresh directory."""
    repo = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("MASDAR_GOLD_PATH", str(repo / "data" / "gold" / "queries.v1.jsonl"))
    return env / "eval"


def test_evaluates_pipelines_and_writes_results(
    eval_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["eval", "--pipeline", "bm25-raw", "bm25", "--out", str(eval_env)]
    assert main([*argv, "--update-baseline"]) == 0
    header = capsys.readouterr().out.splitlines()[0].split()
    assert header == ["pipeline", "nDCG@10", "MRR@10", "R@1", "R@10", "formal", "dialect",
                      "paraphrase"]  # fmt: skip
    written = sorted(path.name for path in (eval_env / "results").iterdir())
    assert written == ["bm25-raw.json", "bm25.json"]
    results = json.loads((eval_env / "results" / "bm25.json").read_text(encoding="utf-8"))
    baseline = json.loads((eval_env / "baseline.json").read_text(encoding="utf-8"))
    assert baseline["overall"] == results["overall"]
    assert len(results["per_query"]) == 82
    assert "`bm25-raw`" in (eval_env / "RESULTS.md").read_text(encoding="utf-8")


def test_baseline_needs_the_default_pipeline(
    eval_env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    argv = ["eval", "--pipeline", "bm25-raw", "--out", str(eval_env), "--update-baseline"]
    assert main(argv) == 1
    assert "--update-baseline needs" in capsys.readouterr().err
    assert not eval_env.exists()


@pytest.mark.usefixtures("eval_env")
def test_search_prints_ranked_citations(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "ما المدة القصوى لفترة التجربة في عقد العمل؟", "-k", "3"]) == 0
    lines = capsys.readouterr().out.splitlines()
    ranked = [line for line in lines if not line.startswith("    ")]
    assert [line[:3] for line in ranked] == [" 1.", " 2.", " 3."]
    assert ranked[0].startswith(" 1. نظام العمل — ")
    assert any("[labor-law:53]" in line for line in ranked)


@pytest.mark.usefixtures("eval_env")
def test_search_reports_an_empty_question(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "   "]) == 1
    assert "error: The question is empty" in capsys.readouterr().err


@pytest.mark.usefixtures("eval_env")
@pytest.mark.parametrize("k", ["0", "-3", "five"])
def test_search_rejects_a_bad_k(k: str) -> None:
    with pytest.raises(SystemExit):
        main(["search", "سؤال", "-k", k])


@pytest.mark.usefixtures("eval_env")
def test_search_says_when_nothing_matches(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["search", "في من"]) == 0
    assert "no matching articles" in capsys.readouterr().out


def test_check_reports_an_unreadable_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["check", str(tmp_path / "missing.txt")]) == 1
    assert "cannot read" in capsys.readouterr().err
