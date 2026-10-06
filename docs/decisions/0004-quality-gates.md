# ADR-0004: Quality gates and what CI really checks

- **Status:** Accepted
- **Date:** 2026-10-06

## Decision
| Gate | Tool | Where |
|---|---|---|
| Lint and format | ruff (strict rule set; see `pyproject.toml`) | pre-commit + CI |
| Types | `mypy --strict` | pre-commit + CI |
| Architecture boundaries | import-linter | pre-commit + CI |
| Tests and coverage of at least 85% | pytest, pytest-cov, Hypothesis | CI |
| Dependency vulnerabilities | pip-audit | CI |
| Secrets | gitleaks | CI |
| Retrieval quality | `make eval` against a committed baseline | see below |

**What the eval gate covers in CI.** Running embedding and reranker models in CI would download
torch and the models on every run. So CI runs the cheap, deterministic part: unit, contract and
integration tests on fakes, plus a BM25-only evaluation smoke test against the gold set. The
full evaluation (dense, hybrid and reranked) runs locally with `make eval`. Its results are
committed under `eval/results/`, and the README table is generated from them.

We call it a full CI eval gate only once one is actually in place.

## Notes
- `RUF001`–`RUF003` (confusable-character warnings) are disabled. They flag Arabic letters as
  look-alikes of Latin ones, which is noise in an Arabic codebase. Invisible and bidi control
  characters are still rejected by `PLE2502` and `PLE2515`.
- Rule for later phases: when an untyped third-party library is added (for example
  `rank-bm25`), its mypy override is scoped to that package only, and it may be imported only
  under `adapters/`.
- Domain purity has two guards. import-linter stops the domain from importing Masdar's outer
  layers, and `tests/unit/test_architecture.py` stops it from importing anything outside the
  standard library.
- `make audit` scans the hash-pinned lockfile export, not the local virtualenv.
