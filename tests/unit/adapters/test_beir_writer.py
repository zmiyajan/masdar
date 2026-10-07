"""Tests for the BEIR writer and dataset card."""

import dataclasses
import json
from pathlib import Path

from masdar.adapters.beir_writer import BeirDatasetWriter, render_dataset_card
from masdar.domain.amendments import ArticleStatus, parse_amendment
from masdar.domain.dataset import DatasetReport, LawSummary, count_statuses
from masdar.domain.models import Article
from masdar.domain.ordinals import ArticleNumber

NOTE = (
    "- صدر المرسوم الملكي رقم (م/44) وتاريخ 1446/2/8هـ (ويعمل بها من تاريخ 1446/8/20هـ) "
    'وعدلت هذه المادة لتكون بالنص الآتي: "نص جديد"'
)
ARTICLE = Article(
    law_id="labor-law",
    law_title="نظام العمل",
    number=ArticleNumber(79, bis=True),
    heading="المادة التاسعة والسبعين مكرر",
    text="نص جديد",
    status=ArticleStatus.AMENDED,
    part="الباب الخامس",
    amendments=(parse_amendment(NOTE),),
)
REPORT = DatasetReport(
    (
        LawSummary(
            "labor-law",
            "نظام العمل",
            "https://example.test/labor",
            "2026-10-07",
            count_statuses([ARTICLE]),
            chunks=1,
        ),
    )
)


def test_writes_beir_corpus_stats_and_card(tmp_path: Path) -> None:
    BeirDatasetWriter(tmp_path).write([ARTICLE], REPORT)

    [line] = (tmp_path / "corpus.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["_id"] == "labor-law:79-bis"
    assert record["title"] == "نظام العمل — المادة التاسعة والسبعين مكرر"
    assert record["text"] == "نص جديد"
    assert record["metadata"]["bis"] is True
    assert record["metadata"]["status"] == "amended"
    assert record["metadata"]["source_url"] == "https://example.test/labor"
    assert record["metadata"]["amendments"] == [
        {
            "kind": "replace",
            "decree": "م/44",
            "issued": "1446/02/08",
            "effective": "1446/08/20",
            "note": NOTE,
        }
    ]

    stats = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert stats["laws"][0]["statuses"]["amended"] == 1
    assert (tmp_path / "DATASET_CARD.md").read_text(encoding="utf-8").startswith("# Saudi")
    assert not list(tmp_path.glob("*.partial"))


def test_arabic_is_written_as_text_not_escapes(tmp_path: Path) -> None:
    BeirDatasetWriter(tmp_path).write([ARTICLE], REPORT)
    assert "نظام العمل" in (tmp_path / "corpus.jsonl").read_text(encoding="utf-8")


def test_card_numbers_come_from_the_report() -> None:
    card = render_dataset_card(REPORT)
    assert "| نظام العمل (`labor-law`) | 0 | 1 | 0 | 0 | 0 | 1 | 1 |" in card
    assert "`corpus.jsonl` holds the 1 current articles" in card
    assert "snapshot 2026-10-07" in card
    assert "Not an official consolidation" in card


def test_repealed_articles_go_to_history_not_to_the_corpus(tmp_path: Path) -> None:
    repealed = dataclasses.replace(ARTICLE, status=ArticleStatus.REPEALED)
    BeirDatasetWriter(tmp_path).write([repealed], REPORT)
    assert (tmp_path / "corpus.jsonl").read_text(encoding="utf-8") == ""
    [line] = (tmp_path / "history.jsonl").read_text(encoding="utf-8").splitlines()
    record = json.loads(line)
    assert record["_id"] == "labor-law:79-bis@repealed"
    assert record["metadata"]["status"] == "repealed"


def test_stats_include_generated_problem_measurements(tmp_path: Path) -> None:
    BeirDatasetWriter(tmp_path).write([ARTICLE], REPORT)
    law = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))["laws"][0]
    assert law["current"] == 1
    assert set(law) >= {"amendment_notes", "outdated_on_portal"}
