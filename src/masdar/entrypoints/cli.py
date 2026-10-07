"""Command-line interface.

Commands:
    ``masdar dataset [--offline] [--refresh] [--laws ...]``: build the dataset.
    ``masdar eval [--pipeline NAME ...] [--lexical] [--update-baseline]``: measure pipelines.
    ``masdar search "سؤال" [-k N]``: print ranked citations.

This module only parses arguments, calls a use case and prints the result. It
is the one place where printing to stdout is the intended output.
"""

import argparse
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from pydantic import ValidationError

from masdar.config import Settings
from masdar.container import (
    LEXICAL_PIPELINES,
    PIPELINES,
    dataset_builder,
    default_search_service,
    eval_results_writer,
    evaluate_use_case,
    search_service,
)
from masdar.domain.dataset import DatasetReport
from masdar.domain.errors import MasdarError
from masdar.domain.evaluation import EvaluationReport
from masdar.domain.models import CURRENT_STATUSES

_EXIT_OK, _EXIT_ERROR = 0, 1
_EXCERPT_CHARS = 160
# The pipeline the regression test guards; it is the one users get by default.
_BASELINE_PIPELINE = "bm25"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    args = _parser().parse_args(argv)
    commands: dict[str, Callable[[argparse.Namespace, Settings], str]] = {
        "dataset": _dataset,
        "eval": _eval,
        "search": _search,
    }
    try:
        output = commands[args.command](args, Settings())
    except (MasdarError, ValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_ERROR
    print(output)
    return _EXIT_OK


def _dataset(args: argparse.Namespace, settings: Settings) -> str:
    with dataset_builder(settings, offline=args.offline, refresh=args.refresh) as build:
        report = build.run(args.laws)
    return _summary(report, str(settings.dataset_dir))


def _eval(args: argparse.Namespace, settings: Settings) -> str:
    default = LEXICAL_PIPELINES if args.lexical else PIPELINES
    names = list(dict.fromkeys(args.pipeline or default))
    if args.update_baseline and _BASELINE_PIPELINE not in names:
        raise MasdarError(f"--update-baseline needs the {_BASELINE_PIPELINE!r} pipeline")
    evaluate = evaluate_use_case(settings)
    reports = [evaluate.run(search_service(settings, name)) for name in names]
    writer = eval_results_writer(args.out or settings.eval_dir)
    written = writer.write(reports)
    lines = [_eval_table(reports), "", *(f"wrote {path}" for path in written)]
    lines.append(f"wrote {writer.summary_path}")
    if args.update_baseline:
        [baseline] = [r for r in reports if r.pipeline == _BASELINE_PIPELINE]
        lines.append(f"wrote {writer.write_baseline(baseline)}")
    return "\n".join(lines)


def _search(args: argparse.Namespace, settings: Settings) -> str:
    results = default_search_service(settings).search(args.question, k=args.k)
    if not results:
        return "no matching articles"
    lines = []
    for result in results:
        excerpt = " ".join(result.matched.text.split())
        if len(excerpt) > _EXCERPT_CHARS:
            excerpt = excerpt[:_EXCERPT_CHARS] + "…"
        lines.append(
            f"{result.rank:>2}. {result.article.citation}  [{result.article.article_id}]  "
            f"{result.score:.2f}"
        )
        lines.append(f"    {excerpt}")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="masdar", description="Masdar command-line tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    dataset = commands.add_parser("dataset", help="build the BEIR corpus and dataset card")
    dataset.add_argument("--laws", nargs="+", metavar="LAW_ID", help="only these laws")
    mode = dataset.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="use committed snapshots only")
    mode.add_argument("--refresh", action="store_true", help="re-download every source page")
    evaluate = commands.add_parser("eval", help="evaluate search pipelines on the gold set")
    evaluate.add_argument(
        "--pipeline",
        nargs="+",
        choices=list(PIPELINES),
        metavar="NAME",
        help=f"pipelines to evaluate (default: all of {', '.join(PIPELINES)})",
    )
    evaluate.add_argument(
        "--lexical", action="store_true", help="only the BM25 pipelines (no ml extra needed)"
    )
    evaluate.add_argument(
        "--out", type=Path, help="output directory (default: MASDAR_EVAL_DIR, else eval/)"
    )
    evaluate.add_argument(
        "--update-baseline",
        action="store_true",
        help=f"record {_BASELINE_PIPELINE!r} as the regression baseline",
    )
    search = commands.add_parser("search", help="search the current law")
    search.add_argument("question", help="the question, in Arabic")
    search.add_argument("-k", type=_positive_int, default=5, help="number of articles (default: 5)")
    return parser


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be at least 1, got {number}")
    return number


def _summary(report: DatasetReport, out_dir: str) -> str:
    lines = [f"{report.name} v{report.version} -> {out_dir}"]
    for law in report.laws:
        current = sum(law.count(status) for status in CURRENT_STATUSES)
        lines.append(
            f"  {law.law_id:<14} {law.total:>4} articles  {current:>4} current  "
            f"{law.chunks:>4} chunks"
        )
    return "\n".join(lines)


def _eval_table(reports: Sequence[EvaluationReport]) -> str:
    styles = list(dict.fromkeys(g.group for r in reports for g in r.by_style))
    header = f"{'pipeline':<26} {'nDCG@10':>7} {'MRR@10':>7} {'R@1':>6} {'R@10':>6}"
    lines = [header + "".join(f" {style:>10}" for style in styles)]
    for report in reports:
        o = report.overall
        by_style = {g.group: g.scores.ndcg_at_10 for g in report.by_style}
        row = (
            f"{report.pipeline:<26} {o.ndcg_at_10:>7.3f} {o.mrr_at_10:>7.3f} "
            f"{o.recall_at_1:>6.3f} {o.recall_at_10:>6.3f}"
        )
        lines.append(row + "".join(f" {by_style.get(s, float('nan')):>10.3f}" for s in styles))
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
