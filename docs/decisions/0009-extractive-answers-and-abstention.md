# ADR-0009: Extractive answers and abstention

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
Users want a direct answer, not a list of articles. The owner's constraint is that this must
work **with no LLM and no API of any kind**: no generated text, no network call, no cost per
query, and nothing that could state something the law does not say. The public demo runs on
a 2-vCPU CPU Space with a budget of about 1.5 s per query (ADR-0007).

## Decision
Answers are **extractive**: Masdar quotes the sentence or sentences of the law that answer the
question, verbatim, with the article as citation, or it says **"not found"**.

| Piece | Module | What it does |
|---|---|---|
| Sentence splitting | `domain/answer.py` `split_sentences` | Units end at a line break (numbered paragraphs `1-`, `أ-` sit on their own lines) or after `.` `؛` `;` followed by whitespace. Units under 4 words merge into a neighbour. Spans over the original text are merged, never strings, so every unit is an exact substring. |
| Evidence invariant | `domain/answer.py` `Evidence` | Construction fails unless `sentence in article.text`. A fabricated quote cannot exist as an object. |
| Answer invariant | `domain/answer.py` `Answer` | `ANSWERED` if and only if there is evidence. `related` (the articles read) is returned in both cases. |
| Answer service | `app/answer.py` `AnswerService` | Searches with the served pipeline, splits the top 3 articles, scores every sentence, quotes up to 2 sentences from the best article, refuses below the threshold. |
| Threshold | `adapters/cross_encoder.py` `DEFAULT_ANSWER_THRESHOLD = -0.75` | Lives next to the model it was calibrated for. |
| Out-of-scope set | `data/gold/out_of_scope.v1.jsonl` | 32 questions the three laws do not answer (see below). |
| Quality | `domain/answer.py` `AnswerQualityReport`, `app/answer.py` `measure_answers` | Attribution, refusal and wrong-answer rates. |

### Why extractive
- **Faithful by construction.** Generation can hallucinate; selection cannot. The worst
  failure is quoting the *wrong* sentence, which the citation makes easy to spot, never a
  sentence the law does not contain. The `Evidence` invariant enforces it in code.
- **No API, no LLM, no new model.** The sentence scorer is the cross-encoder that already
  reranks search results (`CrossEncoderReranker.scorer`, mmarco-mMiniLMv2), so the model is
  loaded once and shared through the `PairScorer` port.
- **CPU latency.** Scoring the sentences of 3 articles is one extra batch of short pairs:
  about 0.07 s on top of search (measured below).

### The answer score
The score of a sentence is

```
cross-encoder logit(question, article location + "\n" + sentence)  +  reranker logit of its article
```

- *Article location* is the same `context_line` the reranker reads (law, part, chapter,
  heading). A bare sentence often lacks its subject ("ولكل من الطرفين الحق ..."); the
  location gives it back.
- *Adding the article's reranker logit*: the reranker read the whole article, so its score is
  evidence that the article is the right one; the sentence score picks the line inside it.
  A plain sum of two logits of the same model has no tuned weight.
- **Extra quotes come only from the best article.** At the chosen threshold, 18 questions had
  a runner-up sentence from another article above the threshold; 15 of those articles were
  not relevant at all (grade 0). Quoting them would add noise under a confident heading.

The service requires a reranked pipeline: the threshold is calibrated on reranker logits, and
a cosine score from a dense-only pipeline would be on another scale.

### How we measured
A throwaway script (not committed) built the served pipeline (`dense+rerank`: mE5-small, 30
candidates, mmarco reranker at its pinned revision) on CPU, read the top 5 articles for every
question and stored every sentence score, then simulated each rule and threshold offline. The
final numbers were re-run end to end through `AnswerService` and `measure_answers` and match
the simulation exactly. Questions: the 82 gold questions (answerable) and the 32 out-of-scope
questions. Machine: Apple M-series, `torch.set_num_threads(2)`, device `cpu`.

Definitions (denominators are explicit because they change the story):
- **Attribution accuracy**: top evidence comes from a grade-2 (answering) article, over all
  82 gold questions. A refusal counts as a miss.
- **Any-relevant accuracy**: the same with grade ≥ 1.
- **False-refusal rate**: gold questions answered "not found", over 82.
- **Wrong-answer rate**: among *answered* gold questions, the share quoting an article judged
  irrelevant. This is the harm metric.
- **Correct-refusal rate**: out-of-scope questions answered "not found", over 32.

### Calibration on held-out data
The threshold is never scored on the questions that chose it. **2-fold cross-validation:**
fold A is the even-indexed gold and out-of-scope questions, fold B the odd-indexed ones. On
each fold the threshold maximising balanced accuracy, ½ (attribution accuracy + correct-refusal
rate), was chosen (at the midpoint to the next lower observed score) and applied to the other
fold. The table pools the two held-out halves, so every question is judged by a threshold that
did not see it.

**1. Scoring rules** (2-fold held-out; ceiling = attribution if nothing were ever refused)

| Rule | Ceiling | Attribution | Any relevant | False refusal | Wrong answer | Correct refusal |
|---|---|---|---|---|---|---|
| sentence only, no location, 3 articles | 0.805 | 0.695 | 0.695 | 0.232 | 0.095 | 0.906 |
| location + sentence, 3 articles | 0.829 | 0.768 | 0.793 | 0.122 | 0.097 | 0.969 |
| location + sentence, best article only | 0.890 | 0.817 | 0.829 | 0.134 | 0.042 | 0.969 |
| location + sentence + 0.25 × article logit, 3 articles | 0.866 | 0.829 | 0.854 | 0.085 | 0.067 | 0.969 |
| **location + sentence + article logit, 3 articles** | **0.890** | **0.829** | **0.841** | **0.146** | **0.014** | **0.969** |

The two best rules tie on the selection objective (0.899). We ship the plain sum: it has
no tuned weight, and its wrong-answer rate is about a fifth of the 0.25 variant (1.4 % against
6.7 %), paid for with 5 more false refusals out of 82. For a legal tool a refusal with the
related articles listed is cheaper than a confident quote from the wrong article. Reading 5
articles instead of 3 changed nothing measurable. The ceiling of 0.890 is the reranker's own
top-1 accuracy: the answer layer cannot quote an article search did not put on top.

**2. The shipped threshold.** The two folds chose **-1.13** and **-0.37**. We ship their
midpoint, **-0.75**. The held-out numbers above are the honest estimate. For reference, the
same rule scored on all 114 questions at -0.75 (**in-sample**, so optimistic) gives:

| Attribution | Any relevant | False refusal | Wrong answer | Correct refusal |
|---|---|---|---|---|
| 0.817 (67/82) | 0.829 (68/82) | 0.171 (14/82) | 0.000 (0/68) | 0.969 (31/32) |

**3. Threshold sweep** (shipped rule, all questions, in-sample)

| Threshold | Attribution | Any relevant | False refusal | Wrong answer | Correct refusal |
|---|---|---|---|---|---|
| -3.0 | 0.854 | 0.866 | 0.098 | 0.041 | 0.844 |
| -2.0 | 0.854 | 0.866 | 0.098 | 0.041 | 0.938 |
| -1.5 | 0.829 | 0.841 | 0.134 | 0.028 | 0.969 |
| -1.0 | 0.829 | 0.841 | 0.146 | 0.014 | 0.969 |
| **-0.75** | **0.817** | **0.829** | **0.171** | **0.000** | **0.969** |
| -0.5 | 0.817 | 0.829 | 0.171 | 0.000 | 0.969 |
| 0.0 | 0.805 | 0.817 | 0.183 | 0.000 | 1.000 |
| 1.0 | 0.744 | 0.756 | 0.244 | 0.000 | 1.000 |
| 2.0 | 0.707 | 0.720 | 0.280 | 0.000 | 1.000 |

The curve is flat between -1.5 and -0.5, so the exact value is not fragile.

**4. Per style at -0.75** (in-sample)

| Style | Questions | Attributed | Refused | Wrong |
|---|---|---|---|---|
| formal | 50 | 47 | 2 | 0 |
| dialect | 17 | 10 | 7 | 0 |
| paraphrase | 15 | 10 | 5 | 0 |
| out-of-scope, formal | 18 | — | 17 | 1 answered |
| out-of-scope, dialect | 14 | — | 14 | 0 answered |

**5. Latency per question** (82 gold questions after one warm-up; CPU, 2 threads)

| Stage | p50 | p95 |
|---|---|---|
| Search only (`dense+rerank`, top 3) | 0.537 s | 0.575 s |
| Full answer (search + split + score sentences) | 0.603 s | 0.800 s |

### The out-of-scope set
32 questions in the gold set's mix of formal Arabic and Saudi dialect: other laws (traffic,
civil service, social insurance and SANED, VAT, rental, personal status, visas, cybercrime,
trademarks), general knowledge, and **near-misses** that sound like Labor Law, PDPL or
Companies Law but are not covered (remote work, housing allowance amount, annual travel
ticket, civil-service maternity leave, CCTV retention, sole-proprietorship registration, zakat
on shares). Each was checked twice: keywords against the corpus text (for example the Labor
Law refers to the social insurance law only for wage deductions and occupational hazards,
never the contribution rate), and by
reading the top sentence the service picks for every question with no threshold. None of
those sentences answers its question. The one out-of-scope question still answered at -0.75
is "annual leave for a government employee under the Civil Service Law", which quotes the
Labor Law's annual-leave article: exactly the near-miss the set was built to expose.

## Consequences and limitations
- **Dialect and paraphrase are refused far more often** (7 of 17 and 5 of 15, against 2 of
  50 formal). The small cross-encoder is less confident on wording it rarely saw, so the
  logits fall under the threshold. The refusal still lists the related articles, but the
  user does not get a quote. A stronger scorer
  (bge-reranker-v2-m3, ADR-0007) would need its own calibration.
- **The answer is only as good as search's first article.** Most remaining misses are
  retrieval misses, for example "كم مدة إجازة الأمومة للموظفة؟", where the reranker ranks
  `labor-law:151` 7th (ADR-0007) and the service correctly refuses rather than quote another
  leave article.
- **One sentence is not always the whole answer.** An answer that spans articles, or a list
  whose lead-in matters ("وفق ما يلي:" followed by `أ-`/`ب-`), is quoted piecemeal. For the
  employer's notice period the service quotes `labor-law:75` but picks paragraph 2 and item
  أ before item ب, which holds the 60 days. The citation and `related` let the user read the
  article; the quote alone may be incomplete.
- **Definitions** are answered line by line (each `الوزارة: ...` line is a unit), which works
  for "what does X mean" but cannot combine two definitions.
- **The threshold is model-specific.** It is a sum of raw logits of mmarco-mMiniLMv2 at the
  pinned revision. Changing the model, revision, truncation or the passage format invalidates
  it; re-run the calibration.
- **The data is small and partly self-made.** 82 gold and 32 out-of-scope questions; one
  out-of-scope question moves the correct-refusal rate by 3 points. The out-of-scope set was
  written by the same author as the system, so it may be easier than real traffic.
- **Selection optimism remains.** The threshold is cross-validated, but the scoring rule
  (location, article term, 3 articles) was chosen among 72 variants on the same pooled
  held-out numbers. The spread among the top rules is small, so the effect is likely small,
  but it is not zero.
- **Abstention is a score, not understanding.** A near-miss that shares the law's words can
  score above the threshold, as the civil-service question shows.
