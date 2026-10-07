"""Write the corpus in BEIR format, with history, stats and a dataset card.

BEIR (Thakur et al., 2021) is the standard layout for retrieval benchmarks:
``corpus.jsonl`` (documents), ``queries.jsonl`` and ``qrels/*.tsv`` (relevance
judgments). Any BEIR tool indexes every line of ``corpus.jsonl``, so that file
holds **current law only**; repealed and superseded articles go to
``history.jsonl``, where nobody indexes them by accident. Queries and qrels are
added with the gold question set.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from masdar.adapters.files import write_atomically
from masdar.domain.amendments import Amendment, AmendmentKind, ArticleStatus
from masdar.domain.dataset import DatasetReport, LawSummary
from masdar.domain.gold import GoldQuery, QueryStyle
from masdar.domain.models import Article

_STATUS_MEANING = {
    ArticleStatus.IN_FORCE: "Never amended; the published text is in force.",
    ArticleStatus.AMENDED: "Amended; the text is the latest full wording from the amendment notes.",
    ArticleStatus.REVIEW_NEEDED: (
        "A partial amendment (one paragraph or phrase) is not applied yet; "
        "the text is the last certain version and the note is attached."
    ),
    ArticleStatus.REPEALED: "Repealed; in `history.jsonl`, not in the corpus.",
    ArticleStatus.SUPERSEDED: (
        "Folded into other articles by a consolidation; its number now belongs to the "
        "new article. In `history.jsonl`, not in the corpus."
    ),
}


class BeirDatasetWriter:
    """Writes ``corpus.jsonl``, ``history.jsonl``, ``stats.json`` and ``DATASET_CARD.md``."""

    def __init__(self, out_dir: Path) -> None:
        """Create a writer that writes into ``out_dir``."""
        self._out_dir = out_dir

    def write(
        self,
        articles: Sequence[Article],
        report: DatasetReport,
        queries: Sequence[GoldQuery] = (),
    ) -> None:
        """Write articles, gold queries with judgments, statistics and the card."""
        self._out_dir.mkdir(parents=True, exist_ok=True)
        urls = {law.law_id: law.source_url for law in report.laws}
        current = [a for a in articles if a.is_current]
        history = [a for a in articles if not a.is_current]
        self._write_jsonl("corpus.jsonl", [to_beir_document(a, urls[a.law_id]) for a in current])
        self._write_jsonl(
            "history.jsonl",
            [to_beir_document(a, urls[a.law_id], doc_id=history_id(a)) for a in history],
        )
        if queries:
            self._write_jsonl("queries.jsonl", [to_beir_query(q) for q in queries])
            (self._out_dir / "qrels").mkdir(exist_ok=True)
            write_atomically(self._out_dir / "qrels" / "test.tsv", to_qrels_tsv(queries).encode())
        stats = json.dumps(to_stats(report), ensure_ascii=False, indent=2) + "\n"
        write_atomically(self._out_dir / "stats.json", stats.encode())
        write_atomically(self._out_dir / "DATASET_CARD.md", render_dataset_card(report).encode())

    def _write_jsonl(self, name: str, records: list[dict[str, Any]]) -> None:
        lines = "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records)
        write_atomically(self._out_dir / name, lines.encode())


def history_id(article: Article) -> str:
    """Id for a non-current article, distinct from the current article with its number.

    Example: ``"labor-law:231@superseded"`` next to the current ``"labor-law:231"``.
    """
    return f"{article.article_id}@{article.status.value}"


def to_beir_document(
    article: Article, source_url: str, *, doc_id: str | None = None
) -> dict[str, Any]:
    """One BEIR record: ``_id``, ``title``, ``text`` plus rich metadata."""
    return {
        "_id": doc_id or article.article_id,
        "title": article.citation,
        "text": article.text,
        "metadata": {
            "law_id": article.law_id,
            "law_title": article.law_title,
            "article_number": article.number.value,
            "bis": article.number.bis,
            "heading": article.heading,
            "article_title": article.title,
            "part": article.part,
            "chapter": article.chapter,
            "status": article.status.value,
            "source_url": source_url,
            "original_text": article.original_text,
            "amendments": [_amendment_record(a) for a in article.amendments],
        },
    }


def to_beir_query(query: GoldQuery) -> dict[str, Any]:
    """One BEIR query record."""
    return {
        "_id": query.query_id,
        "text": query.text,
        "metadata": {"topic": query.topic, "style": query.style.value},
    }


def to_qrels_tsv(queries: Sequence[GoldQuery]) -> str:
    """BEIR relevance judgments: ``query-id``, ``corpus-id``, graded ``score``."""
    rows = ["query-id\tcorpus-id\tscore"]
    rows += [
        f"{query.query_id}\t{article_id}\t{grade}"
        for query in queries
        for article_id, grade in query.relevant
    ]
    return "\n".join(rows) + "\n"


def _amendment_record(amendment: Amendment) -> dict[str, str | None]:
    return {
        "kind": amendment.kind.value,
        "decree": amendment.decree,
        "issued": str(amendment.issued) if amendment.issued else None,
        "effective": str(amendment.effective) if amendment.effective else None,
        "note": amendment.note,
    }


def to_stats(report: DatasetReport) -> dict[str, Any]:
    """Machine-readable counts, mirrored in the dataset card."""
    return {
        "name": report.name,
        "version": report.version,
        "gold_version": report.gold_version,
        "queries": {style.value: count for style, count in report.query_styles},
        "laws": [
            {
                "law_id": law.law_id,
                "title": law.title,
                "source_url": law.source_url,
                "retrieved_on": law.retrieved_on,
                "articles": law.total,
                "current": law.current,
                "statuses": {status.value: count for status, count in law.status_counts},
                "amendment_notes": {kind.value: count for kind, count in law.amendment_counts},
                "outdated_on_portal": law.outdated_on_portal,
                "chunks": law.chunks,
            }
            for law in report.laws
        ],
    }


def render_dataset_card(report: DatasetReport) -> str:
    """The dataset card (Markdown), generated so its numbers never drift."""
    current = sum(law.current for law in report.laws)
    history = report.total() - current
    return "\n".join(
        [
            f"# {report.name} · v{report.version}",
            "",
            "> مجموعة بيانات لاسترجاع المواد النظامية السعودية بالعربية، "
            "مع تطبيق التعديلات النظامية وتوثيق حالة كل مادة.",
            "",
            "Arabic retrieval corpus of Saudi regulations for HR, legal and compliance use. "
            "Every article carries its **status as current law**, because the official portal "
            "publishes the original wording and attaches amendments as notes.",
            "",
            "**Generated by `make dataset`. Do not edit by hand.**",
            "",
            "## Contents",
            "",
            *_status_table(report),
            "",
            f"`corpus.jsonl` holds the {current} current articles; `history.jsonl` holds the "
            f"{history} repealed or superseded ones (ids end in `@repealed` / `@superseded`).",
            "",
            "## Why amendment resolution matters",
            "",
            *_outdated_lines(report),
            "",
            "### Amendment notes by kind",
            "",
            "A note attached to several articles (e.g. a consolidation) is counted once per "
            "article.",
            "",
            *_kind_table(report),
            "",
            *_queries_section(report),
            "## Article status",
            "",
            "| Status | Meaning |",
            "|---|---|",
            *[f"| `{s.value}` | {_STATUS_MEANING[s]} |" for s in ArticleStatus],
            "",
            "## Schema (`corpus.jsonl` and `history.jsonl`, BEIR format)",
            "",
            "| Field | Description |",
            "|---|---|",
            "| `_id` | Stable article id, e.g. `labor-law:79-bis` |",
            "| `title` | Citation, e.g. `نظام العمل — المادة الأولى` |",
            "| `text` | Text in force (see `metadata.status`) |",
            "| `metadata.law_id`, `law_title` | The law |",
            "| `metadata.article_number`, `bis` | Official number; `bis` marks a مكرر article |",
            "| `metadata.heading`, `article_title` | Heading, and the article's own title if any |",
            "| `metadata.part`, `chapter` | Location in the law (الباب / الفصل) |",
            "| `metadata.status` | One of the statuses above |",
            "| `metadata.original_text` | Originally published wording (`null` if added later) |",
            "| `metadata.amendments[]` | `kind`, `decree`, `issued`, `effective` (Hijri), `note` |",
            "| `metadata.source_url` | Official page |",
            "",
            "## Sources",
            "",
            *[_source_line(law) for law in report.laws],
            "",
            "## How it was built",
            "",
            "1. Official HTML pages are fetched (honouring `Crawl-delay: 10`), validated by "
            "parsing, and kept as gzip snapshots with SHA-256 manifests in `data/sources/boe/`.",
            "2. Each article block is parsed (heading, body, amendment notes, part, chapter); "
            "Arabic ordinal headings are converted to numbers.",
            "3. Amendment notes are classified from the text *outside* their quoted new wording "
            "(replace, add, repeal, renumber, consolidate, partial) and applied in decree-date "
            "order. Only unambiguous amendments are applied; partial ones, notes listing several "
            "edits, and undated competing texts mark the article `review_needed`.",
            "4. Integrity check: no two current articles of a law may share a number.",
            "",
            "## Limitations",
            "",
            "- **Not an official consolidation and not legal advice.** Verify against the "
            "official source before relying on any article.",
            "- `review_needed` articles show the last certain wording, not the current one.",
            "- Amendment notes are classified by rules over free text; an unrecognized note "
            "is always treated as partial (never applied), which is the safe failure mode.",
            "- The gold questions have one annotator (drafted with AI assistance, each mapping "
            "verified against the article text). Review by a labor-law practitioner is welcome.",
            "",
            "## License and use",
            "",
            "The law texts are official public documents published by the Bureau of Experts at "
            "the Council of Ministers (هيئة الخبراء بمجلس الوزراء). This dataset adds structure, "
            "amendment resolution and metadata for research and evaluation.",
            "",
        ]
    )


def _queries_section(report: DatasetReport) -> list[str]:
    if not report.queries:
        return []
    styles = ", ".join(f"{count} {style.value}" for style, count in report.query_styles)
    return [
        f"## Queries and relevance judgments (gold set {report.gold_version})",
        "",
        f"`queries.jsonl` holds {report.queries} questions an HR, legal or compliance "
        f"professional would ask ({styles}); `qrels/test.tsv` grades each answering article "
        "`2` and each related article `1`.",
        "",
        f"- `{QueryStyle.FORMAL.value}`: Modern Standard Arabic close to legal wording.",
        f"- `{QueryStyle.DIALECT.value}`: Saudi dialect, as people actually type.",
        f"- `{QueryStyle.PARAPHRASE.value}`: everyday terms the law itself does not use "
        "(e.g. الأوفرتايم, إجازة الأمومة), a direct test of vocabulary mismatch.",
        "",
    ]


def _source_line(law: LawSummary) -> str:
    snapshot = law.retrieved_on or "date unknown"
    return f"- **{law.title}**: <{law.source_url}> (snapshot {snapshot})"


def _status_table(report: DatasetReport) -> list[str]:
    statuses = list(ArticleStatus)
    header = "| Law | " + " | ".join(s.value for s in statuses) + " | Total | Chunks |"
    rows = [
        f"| {law.title} (`{law.law_id}`) | "
        + " | ".join(str(law.count(s)) for s in statuses)
        + f" | {law.total} | {law.chunks} |"
        for law in report.laws
    ]
    return [header, "|---" * (len(statuses) + 3) + "|", *rows]


def _outdated_lines(report: DatasetReport) -> list[str]:
    return [
        f"- **{law.title}**: {law.outdated_on_portal} of {law.current} current articles "
        "have a text in force that differs from the article body the portal displays."
        for law in report.laws
    ]


def _kind_table(report: DatasetReport) -> list[str]:
    kinds = list(AmendmentKind)
    header = "| Law | " + " | ".join(k.value for k in kinds) + " |"
    rows = [
        f"| `{law.law_id}` | "
        + " | ".join(str(dict(law.amendment_counts).get(k, 0)) for k in kinds)
        + " |"
        for law in report.laws
    ]
    return [header, "|---" * (len(kinds) + 1) + "|", *rows]
