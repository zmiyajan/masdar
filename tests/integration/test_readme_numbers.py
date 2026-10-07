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

from masdar.domain.labor_rules import LABOR_RULES

REPO_ROOT = Path(__file__).resolve().parents[2]
README = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

# | `pipeline` | 0.932 | ... |  (bold markers and a trailing note allowed)
_RESULT_ROW = re.compile(r"^\| \**`(?P<name>[^`]+)`\**[^|]*((?:\| \**[0-9.]+\** )+)\|$", re.M)
_NUMBER = re.compile(r"[0-9]+\.[0-9]+|[0-9]+")


def _section(title: str) -> str:
    """The README text under one ``### title`` heading, up to the next heading."""
    start = README.index(f"### {title}")
    end = README.find("\n#", start + 1)
    return README[start : end if end != -1 else None]


def _json(name: str) -> Any:
    return json.loads((REPO_ROOT / "eval" / name).read_text(encoding="utf-8"))


def _cells(row: str) -> list[float]:
    return [float(n) for n in _NUMBER.findall(row)]


def _result(name: str) -> dict[str, Any]:
    path = REPO_ROOT / "eval" / "results" / f"{name}.json"
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def test_results_table_matches_the_evaluation_files() -> None:
    rows = {match["name"]: _cells(match[2]) for match in _RESULT_ROW.finditer(_section("Search"))}
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
    names = [match["name"] for match in _RESULT_ROW.finditer(_section("Search"))]
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


def test_answer_table_matches_the_answer_report() -> None:
    report = _json("answers.json")
    row = next(line for line in _section("Answers").splitlines() if line.startswith("| 82 gold"))
    expected = [
        report["attribution_accuracy"],
        report["wrong_answer_rate"],
        report["false_refusal_rate"],
        report["correct_refusal_rate"],
    ]
    assert _cells(row.split("|", 2)[2]) == pytest.approx(
        [round(value, 3) for value in expected], abs=5e-4
    )


def test_checker_table_matches_the_checker_report() -> None:
    reports = _json("checker.json")
    rows = re.findall(
        r"^\| `([^`]+)` \|[^|]*((?:\| [0-9.]+¹? )+)\|$", _section("Contract checker"), re.M
    )
    assert {name for name, _ in rows} == {"development", "blind-v2"}
    for name, cells in rows:
        kinds = reports[name]["by_kind"]
        expected = [
            kinds["violation"]["precision"],
            kinds["violation"]["recall"],
            kinds["compliant"]["precision"],
        ]
        assert _cells(cells) == pytest.approx([round(v, 2) for v in expected], abs=5e-3), name


def test_counts_in_the_prose() -> None:
    answers = _json("answers.json")
    assert f"| {answers['gold_questions']} gold + {answers['out_of_scope_questions']} " in README
    assert f"{len(LABOR_RULES)} quantitative Labor Law limits" in README
