# Tentative comparison questions — variants 1, 2, 3

Ask each question verbatim to all three dashboards
(`dashboard.py` / `dashboard_v2.py` / `dashboard_v3.py`) and compare the
outputs side by side. Two restaurant names below (CAFE RIO, STELLA GRILL)
are pulled from your actual data so the questions are ready to paste as-is
— substitute others if you want different examples. Out of scope for all
three right now: ratings/reviews, cuisine, price (no review data yet —
see earlier conversation).

Designed as a spread: questions 1-2 are a control (all three variants
should do about equally well), question 3 is where variant 1 should
visibly fall short, and questions 4-5 are where variant 3's structured
output should look most different from 1 and 2 — this maps directly onto
your RQ1 3-condition comparison for the scenario walkthroughs.

---

### 1. Baseline aggregation + chart (control)

> Which 10 restaurants have the most critical violations? Show me a chart.

- **Targets:** basic SQL aggregation + `plot_chart` tool use.
- **Watch for:** all three should produce a similar bar chart and a
  similar top-10 list — this is your control. If variant 3 forces a
  Hypothesis onto a plain ranking question (instead of `hypothesis: none`),
  that's worth noting as over-eager structuring.

### 2. Trend over time + chart

> Has the number of critical violations in Salt Lake County restaurants gone up or down over the last 5 years? Show me a chart.

- **Targets:** temporal SQL reasoning the agent has to construct itself
  (not one of the pre-built overview charts).
- **Watch for:** should be similar across all three; open the "Agent
  reasoning trace" expander on each to compare *how* they built the query,
  not just the final chart.

### 3. Regulatory "why" question — expect a real gap

> A restaurant got cited for Cold Holding. Why does that matter, and what does the food safety rule require?

- **Targets:** RAG access to R392-100 / the SLC county page.
- **Watch for:** variant 1 should decline or answer only vaguely (it has
  no regulatory tool at all) — that's correct behavior, not a bug.
  Variants 2 and 3 should cite specific rule text/section numbers and the
  county's scoring rationale.

### 4. Recommendation / safety judgment

> Is CAFE RIO a safe bet to eat at right now?

- **Targets:** this is where the three should look most visually
  different. CAFE RIO has multiple critical violations across 10
  inspections in your data.
- **Watch for:** variants 1/2 give a free-text opinion grounded in SQL
  numbers (and, for v2, possibly regulatory context) with no explicit
  reasoning structure. Variant 3 should return a structured Hypothesis
  panel (likely `health_risk_concern` or `repeat_critical_violator`) with
  separate supporting/undermining evidence — that panel *is* the visual
  difference to capture.

### 5. Declining-trend warning

> STELLA GRILL's inspection scores have swung a lot over time (10 to 185) — should I be concerned, and would you warn someone away from it?

- **Targets:** trend reasoning (`InspectionTrend.worsening`) feeding into
  a hypothesis (`declining_compliance` or `health_risk_concern`).
- **Watch for:** v1/v2 answer in prose, maybe with a score-over-time
  chart if they choose to plot one. v3 should explicitly name a
  hypothesis type and confidence level, backed by cited evidence rows —
  compare whether the evidence it cites actually supports the trend
  claim or is thin/mismatched.

---

**For the scenario walkthroughs:** screenshot each answer (including the
expanded "Agent reasoning trace") for all three variants per question —
that gives you 15 data points (5 questions × 3 variants) to write up as
your comparison.
