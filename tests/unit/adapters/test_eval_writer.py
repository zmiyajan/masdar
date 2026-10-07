"""Tests for the evaluation results writer."""

import json
from pathlib import Path

import pytest

from masdar.adapters.eval_writer import EvalResultsWriter
from masdar.domain.errors import SourceFormatError
from masdar.domain.evaluation import EvaluationReport, evaluate_query, summarize
from masdar.domain.gold import GoldQuery, QueryStyle


def report(pipeline: str, hit: bool) -> EvaluationReport:
    queries = [
        GoldQuery("q1", "سؤال", (("labor-law:1", 2),), "t", QueryStyle.FORMAL),
        GoldQuery("q2", "سؤال", (("pdpl:4", 2), ("pdpl:5", 1)), "t", QueryStyle.DIALECT),
    ]
    rankings = [["labor-law:1"] if hit else ["labor-law:7"], ["pdpl:5", "pdpl:4"]]
    return summarize(
        pipeline, "v1", [evaluate_query(q, r) for q, r in zip(queries, rankings, strict=True)]
    )


@pytest.fixture
def writer(tmp_path: Path) -> EvalResultsWriter:
    return EvalResultsWriter(tmp_path)


class TestEvalResultsWriter:
    def test_writes_a_stable_machine_readable_file(
        self, writer: EvalResultsWriter, tmp_path: Path
    ) -> None:
        [path] = writer.write([report("bm25", hit=True)])
        assert path == tmp_path / "results" / "bm25.json"
        first = path.read_bytes()
        document = json.loads(first)
        assert list(document) == sorted(document)
        assert document["queries"] == 2
        assert [g["group"] for g in document["by_style"]] == ["formal", "dialect"]
        q2 = document["per_query"][1]
        assert (q2["query_id"], q2["first_answer_rank"], q2["ranking"]) == (
            "q2",
            2,
            ["pdpl:5", "pdpl:4"],
        )
        assert q2["ndcg_at_10"] == round(q2["ndcg_at_10"], 4)
        writer.write([report("bm25", hit=True)])
        assert path.read_bytes() == first  # no timestamps: unchanged runs leave no diff

    def test_results_table_covers_every_pipeline_best_first(
        self, writer: EvalResultsWriter
    ) -> None:
        writer.write([report("weak", hit=False)])
        writer.write([report("strong", hit=True)])  # a later run keeps earlier results
        markdown = writer.summary_path.read_text(encoding="utf-8")
        assert "Do not edit by hand" in markdown
        rows = [line for line in markdown.splitlines() if line.startswith("| `")]
        assert [row.split("`")[1] for row in rows[:2]] == ["strong", "weak"]
        assert "| Pipeline | formal (1) | dialect (1) |" in markdown
        assert "| Pipeline | labor-law (1) | pdpl (1) |" in markdown

    def test_missing_groups_render_as_a_dash(
        self, writer: EvalResultsWriter, tmp_path: Path
    ) -> None:
        writer.write([report("bm25", hit=True)])
        path = tmp_path / "results" / "bm25.json"
        document = json.loads(path.read_text(encoding="utf-8"))
        document["pipeline"], document["by_law"] = "other", document["by_law"][:1]
        (tmp_path / "results" / "other.json").write_text(json.dumps(document), encoding="utf-8")
        writer.write([])
        assert "| `other` | 1.000 | – |" in writer.summary_path.read_text(encoding="utf-8")

    def test_writes_the_baseline(self, writer: EvalResultsWriter) -> None:
        path = writer.write_baseline(report("bm25", hit=True))
        baseline = json.loads(path.read_text(encoding="utf-8"))
        assert (baseline["pipeline"], baseline["gold_version"]) == ("bm25", "v1")
        assert baseline["overall"]["recall_at_10"] == 1.0

    @pytest.mark.parametrize("name", ["", "../escape", "a/b", ".hidden"])
    def test_rejects_names_that_are_not_file_names(
        self, writer: EvalResultsWriter, name: str
    ) -> None:
        with pytest.raises(SourceFormatError, match="file name"):
            writer.write([report(name or " ", hit=True)])

    @pytest.mark.parametrize(
        ("content", "message"),
        [("{oops", "invalid JSON"), ('{"pipeline": "x"}', "not an evaluation result")],
    )
    def test_unreadable_results_fail_loudly(
        self, writer: EvalResultsWriter, tmp_path: Path, content: str, message: str
    ) -> None:
        (tmp_path / "results").mkdir()
        (tmp_path / "results" / "broken.json").write_text(content, encoding="utf-8")
        with pytest.raises(SourceFormatError, match=message):
            writer.write([])
