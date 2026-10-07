# AGENTS.md

Instructions for AI coding assistants (and humans) working on this repository.

## What this is
Masdar is an Arabic-first retrieval engine over Saudi regulations (Labor Law, PDPL,
Companies Law) for HR, legal and compliance teams. The core runs on local models only;
an LLM is optional and only phrases answers from retrieved, cited articles.

## Architecture (enforced, do not bypass)
Ports & adapters. Dependencies point inward only:

```
entrypoints  ->  app (use cases)  ->  ports (Protocols)  ->  domain
                      adapters  ----^ implement ports, use domain
container.py is the only place that wires adapters into use cases.
```

- `domain/`: pure Python. No I/O, no third-party imports, frozen dataclasses.
- `ports/`: `typing.Protocol` interfaces only.
- `adapters/`: the only place third-party libraries (rank-bm25, sentence-transformers,
  anthropic, ...) may be imported.
- `app/`: use cases; depends on ports, never on adapters.
- `entrypoints/`: FastAPI, CLI, MCP server. Thin; no business logic.

`make arch` (import-linter) fails the build if a rule is broken.

## Commands
| Task | Command |
|---|---|
| Install | `make setup` |
| Everything CI runs | `make check` |
| Format + safe fixes | `make fmt` |
| Tests only | `make test` |
| Rebuild dataset offline | `make dataset` |
| Re-download sources (network, 10 s delay) | `make dataset-refresh` |

## Conventions
- Python 3.12, `mypy --strict`, ruff (see `pyproject.toml`). No `Any` in `domain/`.
- Google-style docstrings on every public module, class and function.
- Comments explain *why*, not *what*.
- Raise subclasses of `masdar.domain.errors.MasdarError`; never swallow exceptions.
- Write invisible / control characters as `chr(0x200C)`, never as literal characters.
- Every non-obvious decision gets an ADR in `docs/decisions/`.
- New library? Add it in the phase that needs it; heavy ML packages go in optional extras.
- Never apply an amendment you cannot classify with certainty; mark it `review_needed` (ADR-0005).
- Parsers read; they never mutate the parse tree.
- Changing the golden counts in `tests/integration/test_boe_snapshots.py` requires a reason in the commit message.
- Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`, `refactor:`).

## Definition of done for any change
1. `make check` passes (lint, types, architecture, tests, coverage >= 85%).
2. Tests cover the behaviour, including edge cases.
3. Docs updated: `docs/LEARNING.md` / `docs/INTERVIEW.md` if a concept was added,
   an ADR if a decision was made, `CHANGELOG.md` always.
