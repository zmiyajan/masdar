"""Command-line interface: ``masdar dataset [--offline] [--refresh] [--laws ...]``.

This module only parses arguments, calls a use case and prints the result. It
is the one place where printing to stdout is the intended output.
"""

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from masdar.config import Settings
from masdar.container import dataset_builder
from masdar.domain.dataset import DatasetReport
from masdar.domain.errors import MasdarError
from masdar.domain.models import CURRENT_STATUSES

_EXIT_OK, _EXIT_ERROR = 0, 1


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the process exit code."""
    args = _parser().parse_args(argv)
    try:
        settings = Settings()
        with dataset_builder(settings, offline=args.offline, refresh=args.refresh) as build:
            report = build.run(args.laws)
    except (MasdarError, ValidationError) as error:
        print(f"error: {error}", file=sys.stderr)
        return _EXIT_ERROR
    print(_summary(report, str(settings.dataset_dir)))
    return _EXIT_OK


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="masdar", description="Masdar command-line tools.")
    commands = parser.add_subparsers(dest="command", required=True)
    dataset = commands.add_parser("dataset", help="build the BEIR corpus and dataset card")
    dataset.add_argument("--laws", nargs="+", metavar="LAW_ID", help="only these laws")
    mode = dataset.add_mutually_exclusive_group()
    mode.add_argument("--offline", action="store_true", help="use committed snapshots only")
    mode.add_argument("--refresh", action="store_true", help="re-download every source page")
    return parser


def _summary(report: DatasetReport, out_dir: str) -> str:
    lines = [f"{report.name} v{report.version} -> {out_dir}"]
    for law in report.laws:
        current = sum(law.count(status) for status in CURRENT_STATUSES)
        lines.append(
            f"  {law.law_id:<14} {law.total:>4} articles  {current:>4} current  "
            f"{law.chunks:>4} chunks"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
