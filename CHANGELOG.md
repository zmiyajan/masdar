# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Project scaffolding: uv, Python 3.12, src layout, Makefile, pre-commit, GitHub Actions CI
  (lint, types, architecture, tests, dependency audit, secret scan).
- Domain models `Article`, `Chunk` and `Hit`, with invariants and the `MasdarError` hierarchy.
- `ArabicNormalizer`: configurable, idempotent Arabic normalization for retrieval.
- ADRs 0001–0004, plus the architecture, research, learning and interview docs.
- BOE adapter: catalog, polite HTTP client (10 s crawl delay, OS trust store via `truststore`)
  with committed gzip snapshots and SHA-256 manifests, and a read-only HTML parser.
- Arabic ordinal heading parser (bis and renumbered articles).
- Amendment resolution: replace, add, repeal, renumber and consolidate are applied by decree
  date; partial edits are flagged `review_needed` (ADR-0005).
- Structure-aware chunker with a contextual search prefix.
- `masdar dataset` CLI and `make dataset` / `make dataset-refresh`: BEIR corpus (534 current articles)
  plus `history.jsonl` (42 repealed or superseded), `stats.json` and a generated dataset card.
- Golden tests on the real snapshots, plus an e2e CLI test.
