# Comparison questions — variants 1, 2, 3

25 questions to ask verbatim to all three dashboards (`dashboard.py` /
`dashboard_v2.py` / `dashboard_v3.py`) and compare side by side, for the
RQ1 3-condition comparison (V1 data-only vs. V2 +RAG vs. V3 +ontology
hypothesis/evidence).

**Design principle:** the original 5-question draft only tested cases
where V2/V3's extra machinery could help, never where it could hurt —
that biases the comparison toward "more is better" by construction. This
set is split so RAG/ontology sometimes have nothing to add (or actively
get in the way), same as a real user's mixed question stream would. Each
question names a **predicted winner** and what a *loss* would mean — a
variant winning where it's predicted to lose is the interesting result,
not noise.

- **V1** — `db/food_health.duckdb` only. No RAG, no ontology.
- **V2** — V1 + RAG over R392-100 (Food Service Sanitation Rule) and the
  SLC county inspection-process page.
- **V3** — V2 + ontology-guided structured `HypothesisResponse` (fixed
  hypothesis vocabulary, cited supporting/undermining evidence).

Real establishment names below are pulled live from the actual DB so
these are ready to paste as-is.

---

## A. V1 should win (6) — simplicity wins; RAG/ontology are pure overhead here

Nothing in these questions touches regulation or calls for a judgment
call. A win for V2/V3 isn't really possible; the interesting failure
mode is V2 burning a call on `retrieve_regulation` with nothing relevant
to retrieve, or V3 forcing structure (and losing brevity) on a question
that should be `hypothesis: none`.

### A1. Pure coverage count
> How many total establishments are in the database, and how many have a Salt Lake County health inspection on record?

- **Watch for:** V2 calling `retrieve_regulation` unnecessarily (nothing
  regulatory here — a pure count). V3 padding a two-number answer with
  hypothesis scaffolding it doesn't need.

### A2. Pure attribute lookup
> What's Wingstop's price range and street address?

- **Watch for:** zero health signal in this question at all — any
  variant that brings up inspections/violations unprompted is padding,
  not helping.

### A3. Forced brevity
> Just give me the name of the single restaurant with the most reviews in the database — one line, no explanation.

- **Watch for:** V3's schema (narrative + hypothesis + confidence +
  evidence lists) structurally can't be "one line" — this is where its
  mandatory format is a real UX cost, not a neutral default.

### A4. Explicit "don't judge me" filter question
> List 5 pizza places in Salt Lake County. I just want names and addresses, nothing else.

- **Watch for:** whether V3 respects `hypothesis: none` and stays a
  plain list, or over-elaborates into an unsolicited recommendation.

### A5. Pure category lookup
> What cuisine categories does Cafe Zupas fall under?

- **Watch for:** same as A2 — no regulatory or judgment content
  whatsoever; extra machinery has nothing to contribute.

### A6. Pure hours lookup, chain name (ambiguity trap)
> What are In-N-Out Burger's hours on Sunday?

- **Watch for:** "In-N-Out Burger" alone is ambiguous — 11 Utah
  locations in this DB, only 4 matched to SLCHD records. A good answer
  either asks which location or says so explicitly; picking one
  silently and presenting it as *the* answer is a real failure any
  variant could make, unrelated to RAG/ontology.

---

## B. V2 should win (6) — RAG adds something V1 structurally cannot; V3's mandatory structuring is unneeded since no specific establishment is being judged

V1 should decline or answer only vaguely — that's correct behavior for
it, not a bug. V3 should land close to V2's answer but ideally without
forcing `hypothesis` to anything other than `none`, since these aren't
about a specific establishment's trustworthiness.

### B1. Regulatory "why"
> A restaurant got cited for Cold Holding. Why does that matter, and what does the food safety rule require?

- **Targets:** RAG access to R392-100.

### B2. Scoring mechanics
> What's the difference between a critical and a non-critical violation, and how does each affect an inspection score?

- **Targets:** the county page's 1/3/6-point scoring system, which
  isn't derivable from the DB — `violation_codes.critical` is a flag,
  not a point value.

### B3. Policy, not data
> How often does a restaurant get reinspected after a critical violation, according to the county's own stated policy?

- **Watch for:** V1 can only infer a cadence empirically from raw
  inspection dates (a different and weaker kind of answer) — V2/V3
  should cite the actual risk-level/frequency policy from the RAG page.

### B4. A column's real-world meaning
> If a violation is corrected on-site, does it still count against the inspection score?

- **Targets:** `violations.violation_cos` — the column exists in the DB
  but its scoring consequence is regulatory text, not a queryable value.

### B5. Pure regulatory content, no establishment
> What food safety training or certification requirements exist for food handlers in Salt Lake County?

- Nice callback: "Food Handler Training" is a real `violation_phr` in
  the data (713 occurrences) — V1 can find the violation *exists* but
  not explain the underlying requirement.

### B6. Comparative severity, regulation-only
> Does Utah's food code treat cross-contamination and temperature-control violations differently in terms of severity?

- **Targets:** textbook RAG comparison question; no establishment named,
  so V3 forcing a hypothesis here would be a clear overreach.

---

## C. V3 should win (8) — structured hypothesis + evidence genuinely clarifies a judgment call

These are the cases the ontology was designed for. V1/V2 give a free-text
opinion; V3 should name a `Hypothesis` type, a confidence level, and
separate supporting/undermining evidence. The interesting failure mode
for V3 here is a fabricated or thin evidence citation — check that each
one actually traces to a real tool result.

### C1. Reputation vs. inspection mismatch (real example)
> Is the In-N-Out Burger at 7206 Union Park Ave, Midvale a safe bet to eat at right now?

- Real numbers: 4.5★, 2,840 reviews, but a critical violation on its
  most recent inspection — textbook `reputation_inspection_mismatch`.

### C2. Volatile score history (real example, carried over from the original draft)
> STELLA GRILL's inspection scores have swung a lot over time (10 to 185) — should I be concerned, and would you warn someone away from it?

- Also shows up as a reputation-mismatch candidate (4.5★, 825 reviews,
  critical on latest) — a richer case than it first looks.

### C3. Head-to-head comparison (real example)
> Compare Sagato Bakery & Cafe and Texas Roadhouse — which has the worse track record, and why?

- Real numbers: 47 vs. 38 critical violations. V3's per-entity evidence
  lists make a two-establishment comparison auditable; V1/V2 have to
  narrate both in one paragraph.

### C4. Recommendation with justification (real examples)
> I only care about restaurants with zero critical violations on their most recent inspection. Give me your top pick near downtown Salt Lake City and explain why you trust it.

- Real `safe_bet` candidates in the data: Hub and Spoke Diner, Ice Haus,
  Fisher Brewing Company (all min/max inspection score of 0).

### C5. The 98.4%-uncovered case (real example)
> Maddox Ranch House has a 4.7 rating with almost 6,000 reviews but I can't find any health inspection for it — should that worry me?

- Real: 4.7★, 5,910 reviews, `slchd_establishment_key IS NULL`. Tests
  whether V3 picks `no_inspection_data_available`/`well_reviewed`
  correctly instead of fabricating a risk claim from absence of data.

### C6. Trend + explicit confidence
> Has [an establishment with 3+ inspections]'s compliance been getting better or worse over its history, and how confident are you?

- V1/V2 have no structured confidence field — they'd have to hedge in
  prose. V3's `confidence: low/medium/high` is a direct, comparable answer.

### C7. Spatial + repeat-offender pattern
> I'm looking at opening a restaurant near [a known repeat-violator establishment] — does that area have a lot of repeat health-code offenders nearby?

- Combines `search_establishments`' geo filter with `repeat_critical_violator` evidence — showcases the tools + ontology working together.

### C8. Genuinely conflicting evidence
> Which is riskier to eat at: a restaurant with a high rating but a recent critical violation, or one with no reviews but a clean inspection history?

- Abstract, comparative, evidence-conflicted by design — the
  supporting-vs-undermining split is a real reasoning aid here, not
  decoration.

---

## D. Control (5) — all three should land close to equal

A meaningful gap here is itself a finding — either an inconsistency bug,
or evidence one variant handles "plain" questions worse than baseline.

### D1. (original draft) Baseline aggregation + chart
> Which 10 restaurants have the most critical violations? Show me a chart.

### D2. (original draft) Trend over time + chart
> Has the number of critical violations in Salt Lake County restaurants gone up or down over the last 5 years? Show me a chart.

### D3. Coverage-caveat consistency check
> How many establishments in the database have never had a Salt Lake County health inspection, and what fraction is that?

- Direct regression check on the shared `GROUNDING_POLICY` text (`tools.py`)
  now spliced identically into all three prompts — all three should state
  the ~98.4% figure the same way, unprompted.

### D4. Shared map machinery
> Show me the geographic spread of restaurants with at least one critical violation, on a map.

- `search_establishments` + the map view is the same code path in all
  three variants — should look nearly identical.

### D5. Plain statistic
> What's the average inspection score across all restaurants with SLCHD records, and how does that compare to the median?

---

## Running the comparison

For each question: screenshot the answer (including the expanded "Agent
reasoning trace", and V3's Reasoning tab) for all three variants. That's
75 data points (25 questions × 3 variants). Score each cell against its
**predicted winner**, not just correctness — a technically-correct but
bloated V3 answer on an A-category question is a loss for V3 even if
nothing is factually wrong.
