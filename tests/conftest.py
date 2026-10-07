"""Shared fixtures."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def snapshot_dir() -> Path:
    """The committed source snapshots: real pages from laws.boe.gov.sa."""
    return REPO_ROOT / "data" / "sources" / "boe"
