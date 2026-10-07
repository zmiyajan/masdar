# Masdar · مصدر

**Arabic-first retrieval engine for Saudi regulations, built for HR, legal and compliance teams.**
Ask a question in Arabic and get the exact governing article with a precise citation, from the
Labor Law, the Personal Data Protection Law (PDPL) and the Companies Law.

> محرّك بحث عربي في الأنظمة السعودية لفرق الموارد البشرية والقانونية والامتثال: سؤال بالعربي ← المادة النظامية الدقيقة مع الاستشهاد.

## Why it is hard
- **Arabic breaks naive search.** The same word appears with or without diacritics, with
  different alef and hamza forms, stretched with tatweel, and with Arabic-Indic or Latin
  digits. Exact string matching misses most of these variants.
- **The published text is not the law in force.** The official portal shows each law in its
  original wording and attaches amendments as free-text notes. Indexing it as published would
  serve **50 of 211** current Labor Law articles and **12 of 42** PDPL articles in outdated form
  (measured by `make dataset`, see the [dataset card](data/dataset/DATASET_CARD.md)). Masdar resolves amendments
  (replace, add, repeal, renumber, consolidate) by decree date and flags partial ones instead
  of guessing ([ADR-0005](docs/decisions/0005-amendment-resolution.md)).
- **Compliance needs citations, not paraphrases.** An answer is only useful if it points to
  the exact article.
- **Quality must be measured.** Every retrieval change is scored against a hand-written gold
  set, so improvements are proven with numbers rather than claimed.

## Approach
| Stage | Technique | Status |
|---|---|---|
| Ingestion | Official HTML (هيئة الخبراء), committed gzip snapshots, Arabic ordinal headings to numbers | ✅ |
| Amendments | Versioned articles: text in force derived from decree-dated notes, with a status per article | ✅ |
| Normalization | Rule-based Arabic normalizer (NFKC, diacritics, alef/yaa/taa folding, digits) | ✅ built (defaults to be tuned by ablation) |
| Chunking | Structure-aware (paragraph boundaries) + contextual prefix (law/part/chapter) | ✅ |
| Lexical retrieval | BM25 + Arabic light stemming | planned |
| Dense retrieval | Multilingual E5 embeddings, local | planned |
| Fusion and reranking | Reciprocal Rank Fusion + cross-encoder reranker | planned |
| Evaluation | Recall@k, MRR, nDCG@10 on a versioned gold set; regression gate | planned |
| Interfaces | REST API, CLI, **MCP server** (`search_regulations` tool for AI agents) | planned |

Each technique is tied to its paper in [docs/RESEARCH.md](docs/RESEARCH.md).

## Dataset: Saudi Regulations Arabic Retrieval Benchmark
A BEIR-format corpus of **534 current articles** (plus 42 repealed or superseded ones in
`history.jsonl`), each with its status as current law, its original
wording, and every amendment (decree, Hijri date, note). Full schema and counts are in the
generated [dataset card](data/dataset/DATASET_CARD.md).

| Law | Articles | Current | Amended (applied) | Review needed | Repealed |
|---|---|---|---|---|---|
| نظام العمل (Labor Law) | 252 | 211 | 53 | 18 | 29 |
| نظام حماية البيانات الشخصية (PDPL) | 43 | 42 | 12 | 11 | 1 |
| نظام الشركات (Companies Law) | 281 | 281 | 0 | 0 | 0 |

Queries and relevance judgments (HR and compliance questions) are the next release.

## Results
Retrieval numbers will be published here as each retrieval stage lands. The table is filled
in only from `make eval` output.

## Quickstart
```bash
make setup     # install dependencies (uv) and git hooks
make check     # lint, types, architecture rules, tests
make dataset   # rebuild the corpus offline from committed snapshots (byte-identical)
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
