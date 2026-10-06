# Masdar · مصدر

**Arabic-first retrieval engine for Saudi regulations, built for HR, legal and compliance teams.**
Ask a question in Arabic and get the exact governing article with a precise citation, from the
Labor Law, the Personal Data Protection Law (PDPL) and the Companies Law.

> محرّك بحث عربي في الأنظمة السعودية لفرق الموارد البشرية والقانونية والامتثال: سؤال بالعربي ← المادة النظامية الدقيقة مع الاستشهاد.

## Why it is hard
- **Arabic breaks naive search.** The same word appears with or without diacritics, with
  different alef and hamza forms, stretched with tatweel, and with Arabic-Indic or Latin
  digits. Exact string matching misses most of these variants.
- **Compliance needs citations, not paraphrases.** An answer is only useful if it points to
  the exact article.
- **Quality must be measured.** Every retrieval change is scored against a hand-written gold
  set, so improvements are proven with numbers rather than claimed.

## Approach
| Stage | Technique | Status |
|---|---|---|
| Ingestion | Official structured HTML (هيئة الخبراء), parsed per part, chapter and article | in progress |
| Normalization | Rule-based Arabic normalizer (NFKC, diacritics, alef/yaa/taa folding, digits) | ✅ built (defaults to be tuned by ablation) |
| Chunking | Structure-aware: one article per chunk, with law/part/chapter context | planned |
| Lexical retrieval | BM25 + Arabic light stemming | planned |
| Dense retrieval | Multilingual E5 embeddings, local | planned |
| Fusion and reranking | Reciprocal Rank Fusion + cross-encoder reranker | planned |
| Evaluation | Recall@k, MRR, nDCG@10 on a versioned gold set; regression gate | planned |
| Interfaces | REST API, CLI, **MCP server** (`search_regulations` tool for AI agents) | planned |

Each technique is tied to its paper in [docs/RESEARCH.md](docs/RESEARCH.md).

## Results
The numbers will be published here as each retrieval stage lands. The table is filled in only
from `make eval` output.

## Quickstart
```bash
make setup     # install dependencies (uv) and git hooks
make check     # lint, types, architecture rules, tests
```

## Engineering
- **Architecture:** ports and adapters. The domain is pure Python, and the boundaries are
  enforced in CI by `import-linter`. See [ARCHITECTURE](docs/ARCHITECTURE.md).
- **Quality gates:** ruff (strict), `mypy --strict`, pytest with property-based tests
  (Hypothesis), coverage of at least 85%, dependency audit and secret scanning.
- **Decisions:** every non-obvious choice is recorded as an ADR in
  [docs/decisions](docs/decisions/).

## Documentation
| Doc | For |
|---|---|
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | How the system fits together |
| [RESEARCH.md](docs/RESEARCH.md) | The papers behind each technique |
| [LEARNING.md](docs/LEARNING.md) | Concepts explained step by step (Arabic) |
| [INTERVIEW.md](docs/INTERVIEW.md) | Likely interview questions with answers (Arabic) |
| [AGENTS.md](AGENTS.md) | Rules for contributors and AI assistants |
