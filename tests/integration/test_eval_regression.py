"""Regression gate: the default lexical pipeline must not get worse.

``eval/baseline.json`` holds the overall scores of the default BM25 pipeline,
recorded with ``masdar eval --update-baseline`` and committed. This test
re-runs that evaluation on the committed snapshots (about a second) and fails
if nDCG@10 or Recall@10 drops more than `TOLERANCE` below the baseline. An
improvement passes; record it by updating the baseline in the same commit.
"""

import json
from pathlib import Path

import pytest

from masdar.config import Settings
from masdar.container import LEXICAL_PIPELINES, bm25_search_service, evaluate_use_case
from masdar.domain.evaluation import EvaluationReport

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE = REPO_ROOT / "eval" / "baseline.json"
TOLERANCE = 0.01


@pytest.fixture(scope="module")
def settings(snapshot_dir: Path) -> Settings:
    return Settings(
        snapshot_dir=snapshot_dir, gold_path=REPO_ROOT / "data" / "gold" / "queries.v1.jsonl"
    )


@pytest.fixture(scope="module")
def report(settings: Settings) -> EvaluationReport:
    return evaluate_use_case(settings).run(bm25_search_service(settings))


@pytest.mark.parametrize("metric", ["ndcg_at_10", "recall_at_10"])
def test_default_pipeline_does_not_regress(report: EvaluationReport, metric: str) -> None:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert (baseline["pipeline"], baseline["gold_version"]) == (
        report.pipeline,
        report.gold_version,
    )
    current = getattr(report.overall, metric)
    recorded = baseline["overall"][metric]
    assert current >= recorded - TOLERANCE, f"{metric} fell from {recorded} to {current:.4f}"


def test_every_question_is_scored(report: EvaluationReport) -> None:
    assert len(report.queries) == 82
    assert sum(group.queries for group in report.by_style) == 82


def test_registered_names_are_the_pipeline_names(settings: Settings) -> None:
    # Results files are named after SearchService.name; a mismatch would make
    # `masdar eval --pipeline X` write its results under another name.
    assert {name: build(settings).name for name, build in LEXICAL_PIPELINES.items()} == {
        name: name for name in LEXICAL_PIPELINES
    }
