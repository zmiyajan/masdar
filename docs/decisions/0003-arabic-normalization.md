# ADR-0003: Arabic normalization rules

- **Status:** Accepted (defaults will be revisited with evaluation data)
- **Date:** 2026-10-06

## Context
Queries and documents spell the same word differently: with or without diacritics, with
alef variants, with ى or ي, with ة or ه, with tatweel, and with Arabic-Indic or Latin digits.
Without normalization, lexical retrieval misses these matches.

## Decision
Implemented in `masdar/domain/arabic.py`, applied in this order:

| # | Rule | Always on? | Rationale |
|---|---|---|---|
| 1 | Unicode **NFKC** | yes | Turns presentation forms (ﻻ → لا) and compatibility characters (NBSP) into standard ones (UAX #15) |
| 2 | Remove combining marks: U+0610–U+061A, U+064B–U+065F, U+0670, U+06D6–U+06ED, U+08D3–U+08FF | yes | Diacritics are rare in queries and inconsistent in documents |
| 3 | Remove tatweel U+0640 | yes | Purely visual |
| 4 | Remove invisible format characters: U+00AD, U+061C, U+200B–U+200F, U+202A–U+202E, U+2060–U+2064, U+2066–U+2069, U+FEFF | yes | Invisible characters that break matching |
| 5 | أ إ آ ٱ → ا | default on | Hamza on alef is often omitted when typing |
| 6 | ى → ي | default on | The two letters are commonly confused |
| 7 | ة → ه | default on | Common practice in Arabic IR. Larkey et al. (2002) apply it word-finally inside stemming; we apply it everywhere and let the ablation decide |
| 8 | ؤ → و, ئ → ي | **default off** | Merges distinct words (مسؤول and مسول); to be measured before enabling |
| 9 | ٠-٩ and ۰-۹ → 0-9 | default on | The source uses Arabic-Indic digits, while users often type Latin ones |
| 10 | Collapse whitespace and trim | yes | Stable tokenization |

Rules 1–4 and 10 only remove noise. Rules 5–9 change letters, so each is a switch in
`NormalizationOptions`, and an ablation in the evaluation will decide the final defaults.

- **Normalization is lossy**, so it is applied only to `Chunk.normalized_text` and to queries.
  The original text is kept for display and citations.
- **Idempotence** (`normalize(normalize(x)) == normalize(x)`) is a tested property. It ensures a
  query and an already-normalized document always produce the same form.

- **Known scope limit:** U+0674 (high hamza) is kept. NFKC decomposes the rare letters U+0675
  and U+0678 into a base letter plus U+0674, which does not occur in our sources.

## Alternatives considered
- **CAMeL Tools (Obeid et al., 2020):** richer morphology, but a heavy dependency for rules
  that take about 40 lines. We may revisit it for stemming.
- **Root stemming (Khoja):** too aggressive for legal text, because it merges distinct terms.
  Light stemming (Larkey's light10) is planned for the BM25 tokenizer instead.
