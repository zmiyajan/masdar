# ADR-0005: Resolve amendments into the text in force, conservatively

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
The official portal publishes every law in its **original** wording and attaches each later
amendment as a free-text note in a popup. A compliance tool that indexes the article bodies as
published would confidently cite outdated law. The size of the problem is measured on every
build (`outdated_on_portal` in `data/dataset/stats.json`). On the 2026-10-07 snapshots, **50 of
211** current Labor Law articles and **12 of 42** PDPL articles differ from what the portal
displays.

The notes come in several forms. Exact counts per law are generated into the dataset card:

| Kind | Example wording |
|---|---|
| Full replacement | `عُدلت هذه المادة لتكون بالنص الآتي: "…"` |
| Added article | `أُضيفت هذه المادة …`, `إضافة مادة تحمل الرقم (…)`, `… يكون ترتيبها (…)` |
| Repeal | `أُلغيت هذه المادة`, `تم إلغاء هذه المادة`, `تم إلغاء الباب الرابع عشر` |
| Renumbering | `… ونقلها لتكون (الحادية والثلاثين بعد المائتين)` |
| Consolidation | `تعديل أحكام المواد/المادتين (…) وإعادة صياغتها لتكون في مادتين` |
| Partial edit | `إحلال كلمة "صريحة" محل كلمة "كتابية"`, `عُدلت الفقرة (1)`, or a list of edits (`على النحو الآتي: - … - …`) |

## Decision
1. **Model versions explicitly.** Every `Article` keeps `original_text`, every parsed
   `Amendment` (kind, decree, Hijri issue and effective dates, quoted new text, original note),
   and a `status`. The text in force is *derived* from these and never overwrites the history.
2. **Classify from the text outside the quote.** The kind, decree and dates are read from the
   preamble and any tail after the quoted wording, never from the quoted law text itself.
   Otherwise words inside the new text, such as "إلغاء الفصل", could turn a replacement into a
   repeal.
3. **Apply only what is unambiguous**, in decree-date order (not page order):
   full replacements, added articles (including ones that exist *only* inside another article's
   note, such as article 11 bis), repeals, renumbering, and consolidations. A consolidation gives
   each redrafted article its slice of the new text and marks the rest `superseded`.
4. **Never guess.** Partial edits, notes that list several edits, and competing full texts
   where one is undated all mark the article `review_needed`. The last certain wording is
   kept and the note travels with it. An unrecognized note is treated as partial, so the safe
   behaviour is the default.
5. **Repealed and superseded are terminal.** A later partial edit cannot revive them; only a
   full new text can.
6. **Integrity gate.** The build fails if two current articles of a law share a number.

Found by the independent review (2026-10-07) and fixed with regression tests: an edit-list note
had been applied as a full replacement (Labor 22, PDPL 13), the dual form `المادتين` had been
missed (Labor 152), and an addition worded `يكون ترتيبها` had been missed (Labor 131 bis).

## Consequences
- ✅ Current text for 53 Labor Law articles and 12 PDPL articles that the portal shows only in
  notes, with provenance (decree and date) for every change. A golden test asserts that no
  `amended` text contains amendment-note language.
- ✅ The numbering is fully explained. Every Labor Law number from 1 to 245 is current or
  accounted for, and the bis articles are exactly 11, 79, 131 and 229 bis. Golden tests pin
  both.
- ⚠️ 18 Labor Law and 11 PDPL articles are `review_needed`. They are still searchable, flagged
  as such, and listed in the dataset card. Applying paragraph- and word-level edits
  automatically is the planned next improvement, guarded by golden tests.
- ⚠️ The rules are regular expressions over Arabic legal phrasing. They are tested on real
  notes, and any phrasing they do not recognize fails safe (as `partial`).

## Alternatives considered
- **Index the main text as published:** simple, but it serves about a quarter of the current
  Labor Law (50 of 211 articles) in outdated form. Rejected.
- **Ask an LLM to consolidate the law:** fluent, but unverifiable, and it would invent text
  when uncertain. That is unacceptable as a source of truth. An LLM may later *propose*
  resolutions for `review_needed` articles, but only for human review.
- **Use a third-party consolidated PDF:** not authoritative, and its update cadence is unknown.
  It may serve as a test oracle for a sample of articles.
