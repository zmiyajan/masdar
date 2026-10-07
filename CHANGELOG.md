# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project
uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-10-07

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
- Gold set v1: 82 HR and compliance questions (formal, dialect, paraphrase) with graded
  judgments, exported as BEIR `queries.jsonl` and `qrels/test.tsv`.
- Lexical retrieval: Arabic tokenizer with light10 stemming and stopwords, `Bm25Retriever` (ADR-0006).
- Semantic retrieval: `DenseRetriever` (multilingual-e5-small, cached embeddings),
  Reciprocal Rank Fusion and `HybridRetriever`, `CrossEncoderReranker` (ADR-0007).
- Evaluation: Recall@k, MRR@10 and graded nDCG@10 at article level; `masdar eval` writes
  `eval/results/*.json` and a generated `eval/RESULTS.md`; regression gates for BM25 (CI) and
  the served pipeline (`make test-slow`); a test that keeps README numbers equal to the results.
- One pipeline registry; `MASDAR_PIPELINE` selects what is served (default `dense+rerank`,
  nDCG@10 0.932).
- Interfaces: Arabic web UI, REST API (`/api/search`, `/api/laws`, `/api/health`) with CSP and
  rate limiting, `masdar search`, and an MCP server (`search_regulations`, `get_article`).
- Docker image for Hugging Face Spaces (non-root, CPU-only torch, models baked in) (ADR-0008).
- Extractive answers: `AnswerService` quotes the law's own sentences verbatim with the article
  citation, or answers "not found" below a threshold calibrated on held-out folds; 32
  out-of-scope questions measure abstention (ADR-0009). `GET /api/answer`, `masdar answer`, MCP
  `answer_question`, and an answer card in the web UI.
- Contract and HR-policy checker: clause splitting, Arabic quantity extraction, and
  deterministic verdicts for 16 Labor Law limits pinned to the text in force, with related
  articles per clause (no LLM, no API); a development set and an independently written blind
  set (ADR-0010). `POST /api/check`, `masdar check`, MCP `check_contract`, and a web section.

### Security
- Public demo limits: per-client rate limit keyed on the trusted proxy's `X-Forwarded-For`
  entry, a stricter limit for contract checks, request bodies over 64 KB refused before they
  are read, CSP and security headers on every response including errors, serialised model
  inference, and bounded work per contract (clause length and count).
