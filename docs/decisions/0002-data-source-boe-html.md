# ADR-0002: Use the official HTML from هيئة الخبراء (laws.boe.gov.sa) as the data source

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Arabic PDFs often extract badly: they come out as presentation-form glyphs, in reversed order,
or as scanned images with no text layer. We checked the source before writing any loader.

## Findings (checked 2026-10-06)
- `laws.boe.gov.sa/BoeLaws/Laws/LawDetails/<law-guid>/1` serves the full law as UTF-8 HTML with
  real Arabic text in the U+0600–U+06FF block.
- The structure is explicit in the markup:
  - `<h3>الباب …` is a part and sits outside the article blocks.
  - Each `div.article_item` is one article. It holds an optional `<h3>الفصل …` (chapter), an
    `<h3>المادة …` (heading) and a `div.HTMLContainer` (the body).
  - `div.article_item_popup` holds the **amendment history** and must be excluded from the
    article body.
- The Labor Law page holds 250 article blocks. *Resolved on 2026-10-07:* 246 have a normal
  `المادة …` heading. The other four are two "bis" articles (`( التاسعة والسبعين مكرر )`) and two
  renumbered articles (`(المادة … حالياً) (المادة … سابقاً)`). All 574 headings across the three
  laws parse into numbers (`domain/ordinals.py`).
- **The main text is the original wording; amendments live in popups as free text.** This
  finding drove [ADR-0005](0005-amendment-resolution.md).
- Companies Law headings carry article titles (`المادة الأولى: التعريفات`), which are kept as
  metadata.
- The text uses Arabic-Indic digits (٥٦٠٣٢), so digit normalization is required (ADR-0003).
- `robots.txt` allows these pages and asks for `Crawl-delay: 10`.
- The server does not send its intermediate TLS certificate, so Python's `certifi` bundle
  cannot verify it, while the OS trust store can.

## Decision
- Parse the official HTML; do not use PDF.
- `adapters/boe/` is split into `catalog.py` (laws and URLs), `client.py` (HTTP), `parser.py`
  (HTML to raw blocks) and `source.py` (the `LawSource` port).
- **Snapshots, not a throwaway cache.** Each page is stored gzipped (`<law>.html.gz`) next to
  a manifest (URL, fetch date, SHA-256) in `data/sources/boe/`, **committed to git** (about
  180 KB). Builds are offline and byte-for-byte reproducible. `make dataset-refresh` is the
  only command that contacts the portal, and it waits at least 10 seconds between requests.
- TLS uses the OS trust store via `truststore`, with verification fully on. Disabling
  verification was rejected.
- The parser **never mutates the parse tree**. An earlier version removed popups during the
  walk and corrupted later blocks. Article bodies come only from the article's own
  `HTMLContainer`, never from popups.

## Consequences
- ✅ Clean text and exact article boundaries, so chunking follows the law's real structure.
- ✅ Anyone can rebuild the exact published dataset from the repository alone.
- ⚠️ If the site's markup changes, the parser breaks. Golden tests on the committed snapshots,
  plus parser tests on hand-written HTML, make that a clear failure rather than silent drift.
