# ADR-0006: Lexical retrieval (BM25) and how retrieval is evaluated

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
Masdar has to show with numbers that each retrieval technique earns its place. That requires
two things first: a strong, cheap baseline that every later pipeline (dense, hybrid, reranked)
must beat, and an evaluation harness whose numbers mean what they claim.

## Decision

### BM25 is the baseline
Okapi BM25 (Robertson & Zaragoza, 2009), via `rank_bm25.BM25Okapi` with its defaults
(k1 = 1.5, b = 0.75). On BEIR (Thakur et al., 2021), BM25 beats many dense retrievers out of
domain. Legal questions also often contain the law's own terms, which BM25 matches exactly.
It needs no model, indexes the about 540 chunks in milliseconds, and is fully deterministic,
so it is also what the CI regression gate runs. The index is built in memory at start-up; with
this corpus size a persisted index would only add a cache to keep in sync.

`Bm25Retriever` (`adapters/bm25.py`) takes the text to index (`Chunk.normalized_text` by
default) and one *analyzer* that is applied to documents and queries alike, so the two sides can
never be tokenized differently. Hits with a score of 0 or less are dropped. Ties are broken by
`chunk_id`, so a ranking never depends on corpus order.

### Tokenizer, stopwords and stemmer (`domain/tokenize.py`, stdlib only)
1. **Tokens** are runs of letters and digits (`[^\W_]+`) over normalized text (ADR-0003), so
   punctuation such as `،` and `؟` never sticks to a word.
2. **Stopwords:** 97 function words (prepositions, conjunctions, pronouns, relative and
   interrogative particles), written in standard spelling and passed through the normalizer,
   so the list cannot drift from the indexed form (`على` → `علي`). Content words are never on it,
   including dialect words such as `لازم`. Stopwords are removed **before** stemming.
3. **Light stemming: Larkey, Ballesteros & Connell (2002), light10.**
   - Remove `و` if at least 3 characters remain.
   - Then remove one of `وال بال كال فال لل ال`, longest first, if at least 2 characters remain.
   - Then try each of `ها ان ات ون ين يه ية ه ة ي` once, in that order, removing it if at least
     2 characters remain.

   Larkey et al. found light10 better than root stemming (Khoja) on TREC Arabic data. Roots
   merge too many distinct words, and in legal text that costs precision. Because the default
   normalizer already folds `ة` into `ه`, the `ية` and `ة` suffixes only matter for text
   normalized without that folding.

Stemming and stopwords are switches in `TokenizerOptions`, so each one is measured.

### Metrics (`domain/metrics.py`)
We follow the trec_eval / pytrec_eval conventions that BEIR uses, so the numbers compare with
published work.
- **Relevant** means any positive grade (2 = answers, 1 = related).
- **Recall@k** is the share of relevant articles in the top k (k = 1, 3, 5, 10). It is not capped,
  so a question with more than k relevant articles cannot reach 1.
- **MRR@10** is the mean of 1/rank of the first relevant article, or 0 if none is in the top 10.
- **nDCG@10** (Järvelin & Kekäläinen, 2002) uses linear gain (the grade itself) and a
  `log2(rank + 1)` discount. It is normalized by the ideal ordering of *all* judged articles.
- **First answering rank** (per question) is the rank of the first grade-2 article, or `None`.
  It is stricter than MRR and is kept for error analysis.

Scores are macro-averaged, so every question counts equally. They are reported overall, per
`QueryStyle` and per law. A question counts toward the law of its answering articles.

### Evaluation at the article level
Users cite articles, and the gold set judges articles. Each pipeline therefore runs through
`SearchService`, which collapses chunks to their article's best chunk
(`collapse_to_articles`), and the metrics are computed on that article ranking. This is the
exact code path the API serves, so the numbers describe what users get.

### Results are generated, never hand-written
`masdar eval` writes `eval/results/<pipeline>.json` (sorted keys, 4 decimals, no timestamp, so
an unchanged run leaves no diff). It then regenerates `eval/RESULTS.md` from every file in
`eval/results/`. `masdar eval --update-baseline` records the default pipeline's overall scores
in `eval/baseline.json`. `tests/integration/test_eval_regression.py` re-runs that evaluation in
the normal test suite (about 1 s) and fails if nDCG@10 or Recall@10 drops more than 0.01 below
the baseline.

## Ablation
The gold set is v1: 82 questions (50 formal, 17 dialect, 15 paraphrase). Every pipeline
retrieves 50 chunks, which are collapsed to articles. Each step adds one technique to the one
above it. The exception is `bm25-raw`: it uses the original text and splits only on whitespace,
so the next step adds normalization, punctuation-aware tokenization and stopword removal at once.

| Pipeline | What changes | nDCG@10 | Recall@10 | MRR@10 | formal | dialect | paraphrase |
|---|---|---|---|---|---|---|---|
| `bm25-raw` | original text, whitespace tokens | 0.578 | 0.701 | 0.565 | 0.635 | 0.340 | 0.656 |
| `bm25-normalized` | + normalization (ADR-0003), tokenizer, stopwords | 0.620 | 0.732 | 0.617 | 0.674 | 0.404 | 0.687 |
| `bm25-normalized+context` | + context prefix (law, part, chapter, heading) | 0.634 | 0.768 | 0.625 | 0.700 | 0.423 | 0.654 |
| **`bm25`** (default) | + light10 stemming | **0.797** | **0.890** | **0.792** | 0.862 | 0.644 | 0.751 |
| `bm25-keep-stopwords` | `bm25` without stopword removal | 0.772 | 0.878 | 0.765 | 0.849 | 0.565 | 0.753 |

The style columns are nDCG@10. The full metrics are in `eval/RESULTS.md`.

**Reading the table**
- **Light stemming is the largest gain:** +0.163 nDCG@10, and dialect questions improve from 0.423
  to 0.644. Arabic attaches articles, prepositions and pronouns to words, so without stemming,
  `الإجازات` in a question never meets `إجازة` in the law.
- **Normalization** adds +0.042. Dialect questions gain the most (+0.064), because people type
  without hamza and with `ه` for `ة`.
- **The context prefix** adds +0.014 nDCG@10, within noise, and +0.036 Recall@10. Paraphrase
  questions dip by 0.033, but there are only 15 of them. We keep the prefix: it is what lets
  "in the Labor Law" match an article whose text never names its law (see `domain/chunking.py`),
  and dense retrieval will use the same chunks.
- **Stopword removal: on.** Removing stopwords helps only together with stemming: +0.025 nDCG@10 and
  +0.079 on dialect. Without stemming it is neutral (0.630 kept versus 0.620 removed). The
  mechanism is visible in the stems: light10 turns function words into short pseudo-stems that
  collide with real ones (`علي` → `عل`, `الي` → `ال`, `يكون` → `يك`, `هذه` → `هذ`). The gain
  is only just above the noise threshold below, so the mechanism, not the size of the gain, is
  the main reason for the choice.

## Limitations
- **One annotator, 82 questions.** A single question whose answer slips from rank 1 to rank 2
  moves overall nDCG@10 by about 0.005, so **overall differences under about 0.02 are noise**. Per-style differences are noisier
  still, with only 15 to 17 questions per style.
- The gold set was written while reading the articles, which favours lexical overlap in the
  formal questions. Dialect and paraphrase questions are the fairer test for later pipelines.
- BM25's parameters (k1, b) are library defaults and not tuned. Tuning on 82 questions would
  overfit the gold set.
- Light10 does not handle broken plurals (`عقود` and `عقد` stay distinct). It also sometimes
  strips a letter that belongs to the word: `وزير` becomes `زير` and `والد` becomes `الد`.
  Dense retrieval is expected to cover what affix stripping cannot.

## Alternatives considered
- **Root stemming (Khoja) or a morphological analyzer (CAMeL Tools, Farasa):** heavier and
  slower. Roots over-merge legal terms. Revisit only if light stemming becomes the bottleneck.
- **Pyserini / Lucene's Arabic analyzer:** requires a JVM, which is too heavy for one small
  corpus. Lucene's `ArabicStemmer` implements the same light10 family.
- **pytrec_eval / ir-measures:** standard, but they would add a compiled dependency for about
  40 lines of metrics. The hand-computed unit tests pin our implementation to the same
  definitions.

## References
- Larkey, L. S., Ballesteros, L., & Connell, M. E. (2002). Improving stemming for Arabic
  information retrieval: light stemming and co-occurrence analysis. *SIGIR 2002*.
- Robertson, S., & Zaragoza, H. (2009). The probabilistic relevance framework: BM25 and beyond.
- Järvelin, K., & Kekäläinen, J. (2002). Cumulated gain-based evaluation of IR techniques.
  *ACM TOIS* 20(4).
- Thakur, N., et al. (2021). BEIR: A heterogeneous benchmark for zero-shot evaluation of
  information retrieval models. *NeurIPS Datasets and Benchmarks*.
