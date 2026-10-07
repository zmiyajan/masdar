# ADR-0010: Check contracts with rules as code, pinned to the text in force

- **Status:** Accepted
- **Date:** 2026-10-07

## Context
HR and legal users want to paste an employment contract or an internal HR policy and learn
which clauses conflict with the law. Two things are useful per clause: the articles of the law
in force that relate to it, and a clear verdict where the clause states a quantity the Labor Law
limits (probation length, notice, leave, working hours).

A wrong verdict is costly in one direction. Calling a lawful clause a violation misleads a user
about a real contract. Saying "review needed" only sends them to the cited article. And the law
that counts is the law in force: the portal's main text is outdated for 50 Labor Law articles
(ADR-0005), and several of the limits a contract checker needs are among them.

## Decision
1. **Rules as code, no model and no API.** Each rule (`domain/compliance.py: Rule`) names the
   article, the topic cues, the units it accepts, a ceiling or a floor, and the limit. Matching is
   plain Python over normalized Arabic. Related articles come from the existing `SearchService`,
   which is retrieval only. The same clause always gives the same answer, every verdict cites
   one article, every rule is unit-tested, and nothing leaves the machine.
2. **Quantities are parsed, not guessed** (`domain/quantities.py`). Latin and Arabic-Indic
   digits, number words in both cases with compounds and teens (`مائة وثمانين`, `اثني عشر`),
   duals (`شهرين`), fractions (`نصف شهر`, `ساعة ونصف`) and percentages (`50%`, `%50`,
   `خمسين في المائة`). A number counts only when a unit follows it, so article numbers and
   years (`المادة 75`, `عام 1446`) are never quantities. Every quantity keeps a span into the
   pasted text.
3. **Conservative matching.** A rule fires only when all its cue groups appear **and** a
   quantity of an accepted unit is within 80 characters of the topic cue. On top of that:
   - a number belongs to the topic it is written next to: if another applicable rule's cue is
     strictly closer, the number is left to that rule;
   - for limits per day or per week, a rate word (`يومياً`, `في الأسبوع`) must follow the
     quantity before the next quantity;
   - words just before a quantity can mark it as a condition, not the amount
     (`قبل مرور 6 أشهر`), and are skipped per rule;
   - several quantities with different verdicts give `review_needed`, never a pick;
   - **a violation needs the number to read as the amount the rule is about**: it must follow
     a cue with only linking words between (`إجازة سنوية مدتها 15 يوماً`, `بإشعار كتابي قبل 30
     يوماً`, `بأجر كامل لمدة`), or come right before one (`15 يوماً إجازة سنوية`). Otherwise
     the verdict is `review_needed` (`unclear_role`). Leave and notice clauses are full of other
     numbers: deadlines (`خلال ثلاثة أيام`), carry-over caps, balances, splits and accrual rates
     (`بواقع 2.5 يوم عن كل شهر`). Without this check a floor reads every small number as a breach.
4. **Unit conversion decides only when the whole range agrees.** Weeks to days and years to
   months are exact. A month is 28 to 31 days and a year 354 (Hijri) to 366 days, because Saudi
   contracts use either calendar. The checker converts to a range and decides only when both
   ends fall on the same side of the limit: one month against a 60-day floor is a violation
   (at most 31), three months against a 12-week floor is compliant (at least 84 days), six
   months against a 180-day ceiling is `review_needed` (168 to 186). Hours and percentages
   convert to nothing.
5. **When the clause does not establish the violation, say review needed.** Each rule may list:
   - conditions the limit depends on (`requires_for_violation`): Art. 75's 60-day employer notice
     governs indefinite contracts, so a mutual "30 days' notice" clause that does not say
     `غير محدد المدة` is `review_needed`;
   - words that signal a legal exception (`blocks_violation`): shift work (Art. 100), senior
     posts, guards and cleaners (Art. 108), non-Muslim staff in Ramadan, written consent for loan
     deductions above 10% (Art. 92), a non-monthly wage for notice;
   - an exception margin: Art. 99 lets the minister raise the day to nine hours, so 8 < h ≤ 9 is
     `review_needed` and only more than nine is a violation.
6. **The article's status is part of the rule.** If the article that states a limit is
   `review_needed` in the corpus (a partial amendment not applied, ADR-0005), the rule can only
   return `review_needed`, whatever the clause says. Today that is Art. 107 (overtime pay):
   Royal Decree M/44 (1446) rewrote its first paragraph and the build does not apply partial
   edits. A clause paying 25% overtime is therefore "review needed, the article is under review",
   not a violation. Applying the amendment later turns the rule on by changing one field and the
   pinning test.
7. **Every limit is pinned to the text in force.** `tests/integration/test_labor_rules_pinned.py`
   loads the corpus with `load_current_corpus(Settings())` (offline, committed snapshots) and,
   for every rule, asserts that the article is current, that its heading, status and law title
   equal the rule's, that the rule's `source_phrase` occurs in the text in force (normalized on
   both sides), and that the extractor finds the limit in that text. An amendment that changes
   any of these fails the build instead of leaving the checker citing a stale number.
8. **Only the side the law protects can breach a floor.** Art. 8 voids any condition contrary to
   the law unless it is more favourable to the worker. A shorter notice owed *by the worker* is
   more favourable, so only the employer's notice is checked; a longer leave or a shorter
   probation is always compliant.

## Rules in v1

| rule_id | article | limit | pinned phrase (text in force) | status |
|---|---|---|---|---|
| `probation-max` | labor-law:53 | ≤ 180 days in total | على ألا يزيد مجموع المدة في جميع الأحوال على (مائة وثمانين) يوماً | amended |
| `notice-employer-min` | labor-law:75 | ≥ 60 days | … من طرف صاحب العمل … قبل (ستين) يوماً على الأقل من تاريخ الإنهاء | amended |
| `annual-leave-min` | labor-law:109 | ≥ 21 days | إجازة سنوية لا تقل مدتها عن واحد وعشرين يومًا | in_force |
| `annual-leave-5y-min` | labor-law:109 | ≥ 30 days after 5 years | تُزاد إلى مدة لا تقل عن ثلاثين يومًا إذا أمضى … خمس سنوات متصلة | in_force |
| `daily-hours-max` | labor-law:98 | ≤ 8 h/day (9 → review) | أكثر من ثماني ساعات في اليوم الواحد | in_force |
| `weekly-hours-max` | labor-law:98 | ≤ 48 h/week | أو أكثر من ثمان وأربعين ساعة في الأسبوع | in_force |
| `ramadan-daily-hours-max` | labor-law:98 | ≤ 6 h/day | لا تزيد على ست ساعات في اليوم | in_force |
| `ramadan-weekly-hours-max` | labor-law:98 | ≤ 36 h/week | أو ست وثلاثين ساعة في الأسبوع | in_force |
| `overtime-rate-min` | labor-law:107 | ≥ 50% (always review) | يوازي أجر الساعة مضافًا إليه 50% من أجره الأساسي | **review_needed** |
| `maternity-leave-min` | labor-law:151 | ≥ 12 weeks | إجازة وضع بأجر كامل لمدة (اثني عشر) أسبوعاً | amended |
| `sick-leave-full-pay-min` | labor-law:117 | ≥ 30 days | إجازة مرضية بأجر عن الثلاثين يومًا الأولى | in_force |
| `non-compete-max` | labor-law:83 | ≤ 2 years | ويجب ألا تزيد مدته على سنتين | amended |
| `loan-deduction-max` | labor-law:92 | ≤ 10% | ألا يزيد ما يحسم من العامل في هذه الحالة على 10% من أجره | in_force |
| `hajj-leave-min` | labor-law:114 | ≥ 10 days | لا تقل مدتها عن عشرة أيام | in_force |
| `marriage-leave-min` | labor-law:113 | ≥ 5 days | لمدة (خمسة) أيام عند زواجه | amended |
| `paternity-leave-min` | labor-law:113 | ≥ 3 days | و(ثلاثة) أيام في حالة ولادة مولود له | amended |

Five of these limits differ from the portal's main text: probation (90 → 180 days), employer
notice (30 → 60), maternity leave (10 → 12 weeks), marriage leave (3 → 5 days) and paternity
leave (1 → 3 days). A checker built on the portal text would call a lawful
90 + 90-day probation a violation and a 10-week maternity clause compliant. The labeled set
contains both cases.

Investigated and left out of v1: end-of-service award (Art. 84, half a month per year for the
first five years) needs the service tiers and a clause usually states only one; weekly rest
(Art. 104) is stated as "a day", which does not convert to hours; fixed-term renewal (Art. 55)
changes the contract type rather than setting a limit; the worker's own notice (Art. 75) can only
be compliant under Art. 8.

## Measurement
`data/gold/clauses.v1.jsonl`: 90 clauses in the style of Saudi employment contracts and HR
policies (formal and plain wording, digits and number words), each with the expected findings.
They mix violations, compliant clauses exactly at the limit, unit traps (months against days,
weeks), phrasings that must not fire (negations, waiting periods, confidentiality, rest
periods, overtime hours), and clauses from the PDPL and the Companies Law. A finding is correct
only if both the rule and the verdict match.

| set | clauses | violation P / R | compliant P / R | review P / R | exact clauses |
|---|---|---|---|---|---|
| cl-001…060, first run | 60 | 0.947 / 1.000 | 1.000 / 0.917 | 1.000 / 1.000 | 0.967 |
| cl-061…075, first run (blind batch 1) | 15 | 1.000 / 0.750 | 0.857 / 0.750 | 0.500 / 1.000 | 0.733 |
| cl-076…090, first run (blind batch 2) | 15 | **0.462** / 1.000 | 1.000 / 0.500 | 1.000 / 0.000 | 0.533 |
| all 90, recorded | 90 | **1.000 / 1.000** | 1.000 / 0.941 | 0.846 / 1.000 | 0.967 |

How the numbers were made, honestly: the first 60 clauses were labeled before the checker was
run on them. Their first run produced one false violation (cl-054, a marriage leave read from the
next phrase's number), which led to the phrase-bounded anchor. Two blind batches of 15 were then
written and labeled, and each was run once before any change; those first runs are the best
estimate of quality on unseen wording.

- Batch 1 exposed two general flaws (a rate word belonging to the next number, and a number
  claimed by a farther topic) and two vocabulary gaps (`منافس`, `مدفوعة الأجر بالكامل`).
- Batch 2 targeted ordinary HR-policy sentences with other numbers in leave and notice clauses,
  plus a positive control for each. Its first run gave **7 false violations out of 13** (accrual
  rate, carry-over cap, minimum split, medical-report deadline, Art. 106 emergency hours, notice
  during probation, cash for a leave balance). This is the measured reason for the "amount"
  check in decision 3, the Art. 106 words in the hours exceptions, the probation exception on
  notice, and the carry-over, balance and split words on annual leave. All six positive controls
  are still violations after the change.

The recorded row is measured on clauses that influenced the code, so it overstates quality on new
wording; the blind rows are the honest estimate, and batch 2 shows that untested phrasing can
still produce false violations. Every remaining miss is silence or "review needed", never a wrong
verdict: cl-018 needs each number tied to its party ("30 days for the employee and 60 for the
company"), cl-076 (an accrual rate equal to 30 days a year) and cl-081 (notice during probation)
come out as review needed.

`tests/integration/test_checker_quality.py` holds violation precision at exactly 1.0 and the other
scores within 0.01 of the recorded row.

## Consequences
- ✅ Deterministic, cited, explainable verdicts with no model, no network and no cost per call;
  a whole contract checks in milliseconds.
- ✅ An amendment that changes a limit breaks a test, and an article whose amendment is not
  applied cannot produce a hard verdict.
- ⚠️ Only quantitative Labor Law rules in v1. PDPL and Companies Law clauses get related articles
  but no verdict, and qualitative duties (written form, Arabic language, non-discrimination) are
  not checked.
- ⚠️ Cues are hand-written Arabic phrases. Wording the rules do not know usually produces no
  finding or "review needed", but the second blind batch shows that a number in an unforeseen
  role can still be misread. Quality on unseen wording is lower than the recorded row; every new
  false violation found in use should become a labeled clause and a regression test.
- ⚠️ One annotator wrote and labeled every clause, and the same person wrote the rules. The set
  is small and partly used for development. A second annotator and a larger blind set are the
  next step.
- ⚠️ Clauses are split by lines, numbering, bullets and ordinals. Context in one clause (for
  example "indefinite" in the heading) does not reach the next, which can only turn a violation
  into review needed.

## Alternatives considered
- **Ask an LLM whether each clause is lawful:** fluent, but not reproducible, hard to test, and
  prone to stating limits from its training data, which is exactly the outdated portal wording
  this project exists to avoid. It would also need an API for a feature that does not need one.
  Rejected.
- **Retrieval only (show related articles, no verdicts):** safe, but leaves the user to find the
  number in the article and compare units themselves. Kept as the always-on half of the report.
- **Hard-code limits from the published law:** simple, but the published text is outdated for
  these very articles. Rejected in favour of pinning to the resolved text in force.

## Blind measurement (v1)

`data/gold/clauses.blind.v1.jsonl` holds 40 clauses written by a separate author who saw neither
the code nor the development clauses, only the limits in force. Measured once, before any change
was made because of it:

| Verdict | Precision | Recall |
|---|---|---|
| violation | **1.00** (5/5) | 0.33 (5/15) |
| compliant | 1.00 (13/13) | 0.76 (13/17) |
| review_needed | 0.55 (6/11) | 0.75 (6/8) |

Exact-clause accuracy 0.625. **The checker never called a compliant clause a violation**, which is
the property a compliance tool must have. It missed two thirds of the violations, though: clauses
worded differently from the hand-written cues (bullet lists such as "الزواج: 3 أيام", "عدم منافسة
الشركة … لمدة ثلاث سنوات", loan instalments "تُستقطع … بنسبة 25%") fell to silence or "review needed".
The development numbers above overstate quality; this row is the honest estimate for v1. Recall is
improved in v2 and re-measured on a fresh blind set, so this set is not reused for tuning.

## v2: recall without giving up violation precision

The blind v1 set was **not opened or run** during v2. Only the failure types reported from it were
used, and the fixes are generic matching changes, not wording copied from it. New development
clauses cl-091…125 (one or more per type, plus controls) were written and measured before any
change; then a further 15 (cl-126…140, "blind batch 3") were written after the fixes and run once,
mainly to stress the new, looser mechanisms.

What changed, by failure type:

1. **Labeled lists** ("الزواج: 3 أيام، وفاة …: 5 أيام"): plural `الإجازات`/`إجازات` count as leave
   cues; paternity cues include `ولادة مولود`/`ولادة طفل`. Each number is judged in its own phrase
   (anchors and claims are phrase-bounded), so a bereavement number never reaches marriage leave.
2. **Employer notice**: more ways to name the employer as the party that notifies (`يلتزم الطرف
   الأول`, `تلتزم الشركة بإخطار`, `على الشركة`, …). The indefinite-term condition and the
   probation and non-monthly exceptions are unchanged; a worker's resignation notice still gives
   nothing.
3. **Non-compete**, 4. **loan instalments**, 8. **hajj leave**: a number introduced by an
   explicit measure word in the topic's own phrase now counts as the rule's amount. Possessive
   words (`مدتها`, `ومدتها`, `قدرها`, `نسبته`) refer back to the topic and count for every rule.
   Open ones (`لمدة`, `بنسبة`) can qualify anything in the phrase, so they count only for
   ceilings, where a misread number would have to exceed the limit to do harm. Loan rules also
   accept `تستقطع`, `تقتطع`, `يسترد`.
5. **Sick leave** "أجره كاملاً عن أول N يوماً": possessive full-pay phrases, and `أول` as a link word.
6. **Hours**: exclusion words (`رمضان`, `مولود له`, carry-over, balance, …) now apply to the
   **phrase** holding the number, not the whole clause, so a Ramadan sub-item no longer silences
   the ordinary day. A rule claims a number from another rule only when its own cue is in the
   same phrase and that rule does not exclude the number there. A number followed by the rule's
   rate word ("٥٤ ساعة أسبوعياً") counts as the amount, so the weekly verdict no longer depends
   on the daily one.
7. **Probation**: a total stated *after* the number (`كحد أقصى`, `شاملة`, `بما في ذلك`) is a cap;
   an extension of stated length adds up against 180 days.

General changes that came with these: numbers in a phrase that names the topic are preferred
over numbers elsewhere in the clause; the lead window for condition words grew from 25 to 40
characters but stops at the start of the phrase; annual leave also skips numbers after
`تأجيل` (postponement) and after `طلب`/`تقديم`/`استخدام` (a request, not the entitlement).

| set | clauses | violation P / R | compliant P / R | review P / R | exact |
|---|---|---|---|---|---|
| cl-091…125 before v2 | 35 | 0.889 / 0.421 | 0.857 / 0.353 | 0.200 / 1.000 | 0.400 |
| cl-091…125 after v2 | 35 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 / 1.000 | 1.000 |
| cl-126…140, first run (blind batch 3) | 15 | **0.750** / 1.000 | 1.000 / 0.667 | 0.667 / 0.667 | 0.667 |
| cl-001…090 after v2 (unchanged) | 90 | 1.000 / 1.000 | 1.000 / 0.941 | 0.846 / 1.000 | 0.967 |
| all 140, recorded | 140 | **1.000 / 1.000** | 1.000 / 0.930 | 0.833 / 0.938 | 0.950 |

The single false violation before v2 (cl-125, a carry-over with `لمدة`) was a latent v1 flaw. The
single false violation in blind batch 3 (cl-126, `طلب الإجازة السنوية لمدة 5 أيام`) led to the
request words above and the possessive/open split; it is disclosed here because that fix was
informed by a blind clause. The other blind-3 misses (a bare `أسبوع`, a sick leave stated in
months, a hajj clause with a condition word, a fixed-term non-renewal notice) are silence or
"review needed" and were left as they are. As before, the recorded row is measured on clauses
that shaped the code; the fresh blind v2 set is the real test.
