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
- The Labor Law page holds 250 top-level `article_item` blocks. 246 have an `المادة …`
  heading, and the last one is article 245 (الخامسة والأربعون بعد المائتين). 4 blocks have no
  heading in the expected markup. **Open:** the loader must reconcile the blocks against the
  245 official articles, and a loader test must pin the count.
- The text uses Arabic-Indic digits (٥٦٠٣٢), so digit normalization is required (ADR-0003).
- `robots.txt` allows these pages and asks for `Crawl-delay: 10`.

## Decision
- Parse the official HTML; do not use PDF.
- The loader is an adapter (`adapters/boe_loader.py`), honours a delay of at least 10 seconds
  between requests, caches raw HTML under `data/raw/` (ignored by git), and works offline from
  the cache.
- Article bodies come only from the article's own `HTMLContainer`, never from popups.

## Consequences
- ✅ Clean text and exact article boundaries, so chunking follows the law's real structure.
- ⚠️ If the site's markup changes, the parser breaks. Parser tests run against a saved HTML
  fixture, so a markup change shows up as a clear test failure.
