# ADR-0001: Ports and adapters, with a pure domain

- **Status:** Accepted
- **Date:** 2026-10-06

## Context
Masdar will swap components often, and swapping is the point of the project. BM25 versus dense
retrieval, one embedding model versus another, numpy versus a vector database, and no LLM
versus Claude are all choices the evaluation compares. Tests must run fast and offline.

## Decision
- Split the code into `domain` → `ports` → `app` → `entrypoints`, with `adapters`
  implementing the ports. `container.py` is the single composition root.
- **Domain models are frozen standard-library dataclasses, not Pydantic.** The domain stays
  free of third-party code. Pydantic validates untrusted input at the edges (API requests and
  settings).
- Ports are `typing.Protocol`s (structural typing), so adapters and test fakes do not have to
  inherit from anything.
- `import-linter` enforces the rules in CI. A rule that is not enforced will erode.

## Consequences
- ✅ A new retriever or model means one new adapter plus one line in the container.
- ✅ Use cases are tested against in-memory fakes, with no network and no model downloads.
- ⚠️ The structure costs more upfront than a flat script. We limit that cost by adding a port
  only when a second implementation or a test fake actually needs it.
