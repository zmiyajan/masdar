# Architecture

## Layers
Masdar follows ports and adapters (hexagonal architecture). Dependencies point inward only,
and `import-linter` enforces the rule in CI. The reasoning is in
[ADR-0001](decisions/0001-ports-and-adapters.md).

```mermaid
flowchart LR
    subgraph entrypoints["entrypoints (thin)"]
        API[FastAPI]
        CLI[CLI]
        MCP[MCP server]
    end
    subgraph app["app (use cases)"]
        ING[ingest]
        SRCH[search]
        ANS[answer]
    end
    subgraph ports["ports (Protocols)"]
        P1[Retriever / Embedder / Reranker / VectorStore / LLM]
    end
    subgraph domain["domain (pure)"]
        D1[Article · Chunk · Hit]
        D2[Arabic normalizer · chunking · RRF fusion]
    end
    subgraph adapters["adapters (third-party code lives here)"]
        A1[BOE HTML loader · BM25 · E5 · numpy store · cross-encoder · Claude]
    end
    entrypoints --> app --> ports --> domain
    adapters -.implements.-> ports
    adapters --> domain
```

| Folder | Responsibility | May import |
|---|---|---|
| `domain/` | Models, Arabic text logic, ranking math. No I/O. | stdlib only |
| `ports/` | `typing.Protocol` interfaces the app depends on | `domain` |
| `adapters/` | Concrete implementations (files, models, APIs) | `ports`, `domain`, third-party |
| `app/` | Use cases that orchestrate ports | `ports`, `domain` |
| `entrypoints/` | HTTP, CLI and MCP surfaces | `app`, `container` |
| `container.py` | Composition root: builds adapters and injects them | everything |

## Data flow

**Indexing (offline)**
```
BOE HTML ──loader──► Article ──chunker──► Chunk(text, normalized_text) ──► BM25 index
                                                                     └──► embeddings ──► vector store
```

**Query (online)**
```
question ─► normalize ─┬─► BM25 top-k ──┐
                       └─► dense top-k ─┴─► RRF fusion ─► cross-encoder rerank ─► Hits + citations
```

## Two texts per chunk
Normalization is lossy (for example ة becomes ه), so every `Chunk` carries the original `text`
for display and citations, and a separate `normalized_text` used only for matching. See
[ADR-0003](decisions/0003-arabic-normalization.md).

## Built so far
- `domain/models.py`: `Article`, `Chunk`, `Hit`, each with invariants.
- `domain/arabic.py`: `ArabicNormalizer`, configurable and idempotent.
- `domain/errors.py`: the `MasdarError` hierarchy.
