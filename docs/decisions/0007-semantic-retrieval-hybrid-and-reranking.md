# ADR-0007: Semantic retrieval, hybrid fusion and reranking

- **Status:** Accepted (the hybrid default will be revisited once the project's BM25 is measured)
- **Date:** 2026-10-07

## Context
BM25 only matches words the question shares with the law. Users ask "إجازة الأمومة" while the
Labor Law says "إجازة وضع"; they ask in dialect ("أقدر أحط الموظف تحت التجربة مرة ثانية").
The gold set has 15 *paraphrase* and 17 *dialect* questions for exactly this case. We need a
semantic first stage, a way to combine it with lexical search, and a precise second stage. All
of it must run on local models, and the public demo runs on a 2-vCPU CPU Space with a budget of
about 1.5 s per query.

## Decision

| Component | Module | Choice |
|---|---|---|
| Dense retriever | `adapters/dense.py` | `intfloat/multilingual-e5-small`, `query:`/`passage:` prefixes, display `text` embedded, cosine via dot product of unit vectors |
| Fusion | `domain/fusion.py`, `app/hybrid.py` | Reciprocal Rank Fusion, `k = 60`, optional per-list weights, depth 100 per retriever |
| Reranker | `adapters/cross_encoder.py` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, pairs truncated to 256 tokens, 30 candidates |
| Recommended demo pipeline | wired in `container.py` | **dense + reranker**, `SearchService(candidates=30)` |

### How we measured
A throwaway script (not committed) ran every pipeline through `SearchService`, exactly as users
get it, on the 82 gold questions: 540 chunks of 534 current articles. Chunk hits were collapsed
to articles, keeping the first occurrence. Recall@10 counts grades 1 and 2 as relevant. nDCG@10
uses linear gain (`gain = grade`), as BEIR and pytrec_eval do. BM25 in these runs is a
**minimal stand-in** (`rank-bm25` Okapi, whitespace tokens of `normalized_text`, no stemming),
not the project's BM25 adapter, which was built in parallel. Machine: Apple M-series, 16 GB.

Cells are **Recall@10 / nDCG@10**.

**1. What to embed** (dense only)

| Model · passage text | formal (50) | dialect (17) | paraphrase (15) | all (82) |
|---|---|---|---|---|
| mE5-small · `normalized_text`, normalized query | 0.960 / 0.888 | 0.824 / 0.716 | 0.567 / 0.562 | 0.860 / 0.792 |
| **mE5-small · `text`, raw query** | 0.980 / 0.904 | 0.912 / 0.796 | 0.933 / 0.798 | **0.957 / 0.862** |
| mE5-small · context line + `text` | 0.960 / 0.888 | 0.912 / 0.770 | 0.933 / 0.748 | 0.945 / 0.838 |
| mE5-base · `normalized_text`, normalized query | 0.960 / 0.866 | 0.824 / 0.802 | 0.833 / 0.669 | 0.909 / 0.817 |
| mE5-base · `text`, raw query | 0.990 / 0.908 | 0.912 / 0.832 | 0.900 / 0.802 | 0.957 / 0.873 |
| mE5-base · context line + `text` | 0.980 / 0.903 | 0.912 / 0.863 | 0.933 / 0.712 | 0.957 / 0.860 |

Letter folding (ة → ه, ى → ي) helps BM25 but hurts the bi-encoder: it produces spellings the
model rarely saw in pre-training, and paraphrase recall falls from 0.93 to 0.57. The context
prefix that helps BM25 (ADR-0003) dilutes the embedding of a short article. mE5-base is only
+0.011 nDCG over mE5-small, for 2.4× the parameters, 3× the CPU query time and about 2.2× the disk (1.05 GB against
0.47 GB). So
the default is **mE5-small embedding the display `text`**.

**2. Pipelines** (30 candidates; rerankers read "law location + text")

| Pipeline | formal | dialect | paraphrase | all (82) |
|---|---|---|---|---|
| BM25 (minimal stand-in) | 0.840 / 0.677 | 0.471 / 0.373 | 0.733 / 0.656 | 0.744 / 0.610 |
| Dense mE5-small | 0.980 / 0.904 | 0.912 / 0.796 | 0.933 / 0.798 | 0.957 / 0.862 |
| Dense mE5-base | 0.990 / 0.908 | 0.912 / 0.832 | 0.900 / 0.802 | 0.957 / 0.873 |
| Hybrid RRF (BM25 + mE5-small), equal weights | 0.890 / 0.818 | 0.706 / 0.557 | 0.800 / 0.733 | 0.835 / 0.749 |
| Hybrid RRF, weights 0.5 / 1 (sensitivity only) | 0.910 / 0.824 | 0.765 / 0.609 | 0.867 / 0.743 | 0.872 / 0.765 |
| **Dense + mmarco reranker** | 0.980 / 0.959 | 0.912 / 0.923 | 1.000 / 0.853 | **0.970 / 0.932** |
| Hybrid + mmarco reranker | 0.950 / 0.945 | 0.824 / 0.799 | 0.867 / 0.801 | 0.909 / 0.888 |
| Dense + bge-reranker-v2-m3 | 0.980 / 0.969 | 0.912 / 0.941 | 1.000 / 0.922 | 0.970 / 0.955 |
| Hybrid + bge-reranker-v2-m3 | 0.960 / 0.948 | 0.824 / 0.851 | 0.867 / 0.824 | 0.915 / 0.905 |

Candidate-pool recall (relevant articles inside the 30 chunks handed to the reranker):
BM25 0.811, dense 0.976, hybrid 0.915. A reranker can only reorder what it is given, so the
stronger pool wins after reranking too.

**3. Reranker input and truncation** (mmarco, hybrid first stage, nDCG@10 over all 82)

| Variant | nDCG@10 | 2-thread CPU p50 |
|---|---|---|
| `text` only, 512 tokens | 0.865 | n/a |
| law location + `text`, 512 tokens, 30 candidates | 0.879 | 1.48–1.60 s |
| law location + `text`, 384 tokens, 30 candidates | 0.885 | 1.13 s |
| **law location + `text`, 256 tokens, 30 candidates** | **0.888** | **0.57 s** |
| law location + `text`, 256 tokens, 20 candidates | 0.836 | 0.35 s |

bge-reranker-v2-m3 showed the same pattern: 0.889 with `text` and 0.905 with location + text.
A batch is padded to its longest pair, so a few long articles set the cost of all 30; most
articles are short (median 60 words), so cutting at 256 tokens costs nothing measurable.

**4. Latency per query** (82 queries after one warm-up; CPU = `torch.set_num_threads(2)`)

| Stage | CPU, 2 threads: p50 / p95 | Apple MPS: p50 / p95 |
|---|---|---|
| Embed one query, mE5-small | 0.005 / 0.006 s | 0.006 / 0.011 s |
| Embed one query, mE5-base | 0.015 / 0.017 s | not measured |
| Rerank 30, mmarco-mMiniLMv2 (256 tokens) | **0.548 / 0.558 s** | 0.269 / 0.321 s |
| Rerank 30, bge-reranker-v2-m3 (256 tokens) | 3.90 / 4.00 s (10 queries) | 3.15 / 4.61 s |

The CPU figures approximate the 2-vCPU Space by limiting an M-series CPU to two threads; a
cloud vCPU is usually slower per thread, so expect the Space to be somewhat slower than this.
The bge MPS figure was taken on a 16 GB machine under memory pressure and is pessimistic. It
does not change the decision: bge is over the budget on CPU by a factor of about 2.6.

### Recommended defaults
- **Public demo (CPU): dense mE5-small → mmarco reranker, 30 candidates.** Best measured quality
  that fits the budget: nDCG@10 0.932 against 0.862 for dense alone and 0.610 for the BM25
  stand-in. About 0.55 s of reranking plus about 5 ms of query embedding on two CPU threads.
- **Quality option (GPU or a patient user):** the same pipeline with `BAAI/bge-reranker-v2-m3`,
  nDCG@10 0.955 (2.2 GB download).
- **Hybrid stays available but is not the default yet.** With the BM25 stand-in, equal-weight
  RRF lowered nDCG@10 from 0.862 to 0.749, mostly on dialect questions where BM25 is weakest.
  The decision must be re-run with the project's real BM25 through the evaluation harness. If
  hybrid then wins, switching is one line in `container.py`.

### Why RRF fuses ranks, not scores
BM25 scores are unbounded sums of term weights whose scale changes with the query. Cosine
similarities sit in a narrow band near the top (0.84–0.87 for the top six maternity hits).
Adding raw scores lets whichever retriever has the wider spread decide alone. Min-max
normalization depends on each query's outliers. RRF (Cormack, Clarke & Büttcher, 2009) uses only
ranks: each list adds `weight / (k + rank)`, `k = 60` damps the advantage of the very first
ranks, and the method needs no training data. We have 82 questions, which is too few to tune a
learned fusion without overfitting. Implementation details:
- each hit's own `rank` is used, not its list position;
- a chunk that appears twice in one list counts once, at its best rank;
- ties are broken by `chunk_id`, so the output never depends on the order of the input lists.

### Why the reranker sits after fusion
A cross-encoder reads the question and the passage together, which is accurate but costs a
full transformer pass per pair. It cannot score all 540 chunks per query. Bi-encoders and BM25
are cheap and recall-oriented; the cross-encoder is expensive and precision-oriented (Nogueira &
Cho, 2019). Fusion (or dense alone) builds the best candidate pool, and the reranker orders it.
Reranking each list before fusing would cost twice as much and then throw the scores away again
when RRF keeps only ranks. `SearchService` applies the law filter before reranking, so no
reranker time is spent on candidates that will be dropped.

### Embedding cache
- File: `data/index/<model-slug>-<fingerprint>.npy`, for example
  `intfloat-multilingual-e5-small-1a2b3c4d5e6f7a8b.npy`. `data/index/` is gitignored.
- Fingerprint: SHA-256 over every chunk id and the **exact string embedded** (prefix included),
  joined with ASCII unit and record separators, truncated to 16 hex digits. Any change to the
  corpus, the chunking, the embedded field or the prefix gives a new file name, so a stale
  cache can never be read. Two models never share a file because the slug differs.
- Written to a temporary file in the same directory and renamed, so an interrupted run never
  leaves a truncated cache. A file whose row count does not match is re-embedded.
- Old files are not garbage-collected; deleting `data/index/` is always safe.
- Start-up on MPS, measured: about 9 s to load mE5-small and embed 540 chunks without a cache,
  about 5 s with it (all of it model loading). Loading the reranker adds about 2.6 s.

### Testability and boundaries
`DenseRetriever` takes an `Encoder` and `CrossEncoderReranker` takes a `PairScorer` (small
Protocols inside each adapter), so unit tests use deterministic fakes with no model download.
`torch` and `sentence-transformers` are imported lazily inside the real wrappers. CI installs
without the `ml` extra, and the modules and their unit tests still import and run there. Real
models are covered by `@pytest.mark.slow` tests (`make test-slow`).

## Consequences and limitations
- **The gold set is small** (82 questions; 15 paraphrase, 17 dialect). One question moves a
  per-style score by 0.06–0.07, so differences of a few hundredths are noise. The mE5-small
  versus mE5-base gap is within that noise.
- **The model choices were made on the same gold set that reports the results.** There is no
  held-out split, so the reported numbers are somewhat optimistic. Only coarse choices were
  made (model, text field, truncation), and no fusion weights were tuned.
- **The hybrid verdict depends on a BM25 stand-in.** It must be re-checked with the real
  adapter.
- **The small reranker can hurt individual paraphrases.** For "كم مدة إجازة الأمومة للموظفة؟"
  dense ranks `labor-law:151` first, and mmarco moves it to 7th: it does not link "الأمومة" to
  "وضع". bge-reranker-v2-m3 ranks it 2nd. The slow test only guards that the answer stays in
  the top 10.
- **Truncation:** mE5 reads at most 512 tokens and the reranker 256, so the tail of the longest
  articles (definitions, penalty tables, up to about 330 words) is not seen by either model.
  Chunking keeps most articles far below that.
- **Latency is approximate.** It was measured on an M-series CPU limited to two threads, not on
  the Space itself. Model loading happens once at start-up, not per query (see the cache
  section for the measured times).
- `gte-multilingual-reranker-base` was not evaluated. It requires `trust_remote_code=True`,
  which executes code from the model repository, and we do not want that in an open-source
  default.
- Both default models together are about 0.94 GB on disk (0.47 GB each); bge-reranker-v2-m3
  adds 2.15 GB.
