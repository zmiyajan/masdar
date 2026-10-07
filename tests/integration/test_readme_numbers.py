"""The README's numbers must be the generated ones, never typed by hand.

Results come from ``eval/results/*.json`` (``make eval``) and dataset counts
from ``data/dataset/stats.json`` (``make dataset``). If either changes, these
tests fail until the README is updated to match.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

# | `pipeline` | 0.932 | ... |  (bold markers and a trailing note allowed)
_RESULT_ROW = re.compile(r"^\| \**`(?P<name>[^`]+)`\**[^|]*((?:\| \**[0-9.]+\** )+)\|$", re.M)
_NUMBER = re.compile(r"[0-9]+\.[0-9]+|[0-9]+")


def _cells(row: str) -> list[float]:
    return [float(n) for n in _NUMBER.findall(row)]


def _result(name: str) -> dict[str, Any]:
    path = REPO_ROOT / "eval" / "results" / f"{name}.json"
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def test_results_table_matches_the_evaluation_files() -> None:
    rows = {match["name"]: _cells(match[2]) for match in _RESULT_ROW.finditer(README)}
    assert "dense+rerank" in rows, "README results table not found"
    for name, cells in rows.items():
        result = _result(name)
        overall = result["overall"]
        dialect = next(g for g in result["by_style"] if g["group"] == "dialect")
        expected = [
            overall["ndcg_at_10"],
            overall["recall_at_10"],
            overall["mrr_at_10"],
            dialect["ndcg_at_10"],
        ]
        assert cells == pytest.approx([round(value, 3) for value in expected], abs=5e-4), name


def test_served_pipeline_is_the_best_in_the_table() -> None:
    served = re.search(r"\*\*`(?P<name>[^`]+)`\*\* \(served\)", README)
    assert served is not None
    names = [match["name"] for match in _RESULT_ROW.finditer(README)]
    best = max(names, key=lambda name: _result(name)["overall"]["ndcg_at_10"])
    assert served["name"] == best


def test_dataset_table_matches_the_stats() -> None:
    stats = json.loads((REPO_ROOT / "data" / "dataset" / "stats.json").read_text("utf-8"))
    for law in stats["laws"]:
        row = next(line for line in README.splitlines() if line.startswith(f"| {law['title']}"))
        statuses = law["statuses"]
        expected = [
            law["articles"],
            law["current"],
            statuses["amended"],
            statuses["review_needed"],
            statuses["repealed"],
        ]
        assert [int(n) for n in _NUMBER.findall(row.split("|", 2)[2])] == expected, law["law_id"]
