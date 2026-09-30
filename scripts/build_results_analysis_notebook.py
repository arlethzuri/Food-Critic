"""Builds and executes results_analysis.ipynb at the project root.

Loads every run under results/frontend/*_runs/, grades the 17 factual
question/thread-turns against ground_truth_answers.ipynb (hybrid: rule-based
pass + baked-in manual overrides for cases the rules can't resolve --
see MANUAL_OVERRIDES below), categorizes failed runs, and selects
best/worst qualitative examples. Writes figures to figs/ and a summary to
results_summary.json -- both feed results_section.tex and supp.tex directly,
so rerun this after any change to results/frontend/ before touching those.

Source of truth: this script, not the generated .ipynb -- to change a
grading rule, an override, or a figure, edit here and rerun.

  .venv/bin/python scripts/build_results_analysis_notebook.py
  MPLBACKEND=Agg .venv/bin/jupyter nbconvert --to notebook --execute --inplace results_analysis.ipynb

MPLBACKEND=Agg matters: the notebook's plt.show() calls block forever under
an interactive matplotlib backend (e.g. MacOSX) with no display attached.
"""
import nbformat as nbf
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell

nb = new_notebook()
cells = []

def md(text):
    cells.append(new_markdown_cell(text))

def code(text):
    cells.append(new_code_cell(text))

# ============================================================ Header
md("""# Results analysis

Loads every run under `results/frontend/*_runs/`, grades the 17 factual
question/thread-turns against `ground_truth_answers.ipynb`, categorizes failed
runs, selects best/worst qualitative examples, and generates the figures/tables
for `results_section.tex`.

**Grading method (hybrid):** a rule-based first pass per question (keyword/number
checks against the ground-truth facts), then every case the rules couldn't
resolve confidently was read in full and hand-labeled — see the
`MANUAL_OVERRIDES` dict below, each with its justification. 0 runs were left
ungraded.""")

# ============================================================ Setup
code("""import glob
import json
import re
import shutil
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(".").resolve()
FIGURES_DIR = ROOT / "figures"
FIGURES_DIR.mkdir(exist_ok=True)
(FIGURES_DIR / "qualitative_examples").mkdir(exist_ok=True)

plt.rcParams.update({"font.size": 10, "figure.dpi": 150})
""")

md("## Load runs")
code("""rows = []
for p in glob.glob(str(ROOT / "results/frontend/*_runs/*.json")):
    d = json.load(open(p))
    rows.append({
        "path": p,
        "provider": d.get("provider"),
        "model": d.get("model"),
        "variant": d.get("variant"),
        "question_raw": d.get("question", ""),
        "output_text": d.get("output_text") or "",
        "success": d.get("success"),
        "error": d.get("error"),
        "chart_image_files": d.get("chart_image_files") or [],
        "estimated_cost_usd": d.get("estimated_cost_usd"),
        "duration_seconds": d.get("duration_seconds"),
    })
runs = pd.DataFrame(rows)
print(f"loaded {len(runs)} runs across {runs['provider'].nunique()} providers")
runs.groupby("provider").size()""")

md("""## Map each run to a canonical question ID

Every run in this dataset is a `*_memory` variant (all questions -- including
the single-turn ones -- were run through the memory-enabled dashboards), so
runs are matched to questions by comparing question text, not variant name.
One question in the source data (`Which street has the highest number of 3
star restaurants?`) has a duplicate with a stray leading invisible character
from a copy-paste -- stripped by `norm_q` before matching.""")
code("""def norm_q(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^[^\\w]+", "", s)
    return s.replace("\\u2019", "'").replace("\\u2018", "'").strip()

runs["question_norm"] = runs["question_raw"].map(norm_q)

QUESTIONS = {
    "Q1": "Which restaurant/restaurants violated health/food codes most?",
    "Q2": "Is there any correlation between ratings and violations among the restaurants?",
    "Q3": "Give me the name of the single restaurant with the most reviews in the database, along with its full violation history.",
    "Q4": "Find me the restaurant with the most reviews that has had a violation.",
    "Q5": "What does an inspection score mean?",
    "Q6": "What's the difference between a critical and a non-critical violation, and how does each affect an inspection score?",
    "Q7": "Is the In-N-Out Burger a safe bet to eat at right now? Show detailed visual analytics to answer this.",
    "Q8": "STELLA GRILL's inspection scores have fluctuated significantly over time. Should I be concerned? Answer with very detailed visual analytics.",
    "Q9": 'What does the issue category "cold holding" mean?',
    "Q10": "Show me the geographic spread of restaurants with at least one critical violation, on a map.",
    "Q11": "Show me detailed visual analytics and statistics of inspection scores across all establishments.",
    "Q12": "For which restaurants has the number of critical violations increased, and for which has it decreased over the last 5 years? Show me a detailed visual analysis.",
    "Q13": "Which street has the highest number of 3 star restaurants?",
    "Q14": "Between Thai and Korean restaurants, which cuisine has the higher average rating? Which one has more violations?",
    "Q15": "I'm in the mood for breakfast, but don't feel like traveling far out of Rose Park. What do you recommend? I don't like sweet breakfasts.",
    "ThreadA_T1": "How many establishments have a Salt Lake County health inspection on record?",
    "ThreadA_T2": "Among them, can you show me the distribution and timeline of health inspections?",
    "ThreadB_T1": "Compare the highest rated Chinese restaurant against the most reviewed Chinese restaurant.",
    "ThreadB_T2": "Which do you recommend I try?",
    "ThreadC_T1": "How hard is it to find halal food options in Salt Lake County?",
    "ThreadC_T2": "If I like vegetables, which do you recommend I try?",
}
NORM_QUESTIONS = {qid: norm_q(txt) for qid, txt in QUESTIONS.items()}

def match_qid(q_norm: str):
    q_norm = q_norm.replace("\\u2019", "'")
    for qid, ref in NORM_QUESTIONS.items():
        if q_norm == ref or q_norm.startswith(ref[:60]):
            return qid
    return None

runs["qid"] = runs["question_norm"].map(match_qid)
assert runs["qid"].isna().sum() == 0, "unmatched questions found"
print("all", len(runs), "runs matched to a canonical question ID")
runs["qid"].value_counts()""")

# ============================================================ Failure analysis
md("""## Failed runs

Categorized by root cause. `groq_project_model_blocked` is a Groq console
project-permission setting (`llama-3.3-70b-versatile` disabled at the project
level), not a model or code failure -- separated out from genuine capability
failures.""")
code("""fails = runs[runs["success"] == False].copy()

def categorize(err):
    if not isinstance(err, str):
        return "unknown"
    if "model_permission_blocked_project" in err or "blocked at the project level" in err:
        return "groq_project_model_blocked (infra/quota -- not a model failure)"
    if "tool call validation failed" in err or "tool_use_failed" in err:
        return "malformed_tool_call_args (model emitted invalid JSON types for tool args)"
    if "Schema is too complex" in err or "Grammar compilation timed out" in err:
        return "schema_too_complex (Anthropic V3 combined tool+structured-output schema)"
    if "temperature` is deprecated" in err:
        return "temperature_deprecated (stale server process -- fixed in app/llm.py, needs dashboard restart)"
    if "rate_limit" in err.lower() or "RateLimitError" in err:
        return "rate_limit"
    if "UNAVAILABLE" in err or "overloaded" in err.lower() or "529" in err:
        return "provider_overloaded (transient 5xx)"
    return "other"

fails["category"] = fails["error"].map(categorize)
failure_summary = fails.groupby(["provider", "category"]).size().rename("n").reset_index()
print(f"{len(fails)} failed runs out of {len(runs)} total ({len(fails)/len(runs):.1%})")
failure_summary""")

code("""fail_rate_by_provider = runs.groupby("provider")["success"].agg(["sum", "count"])
fail_rate_by_provider["success_rate"] = fail_rate_by_provider["sum"] / fail_rate_by_provider["count"]
fail_rate_by_provider = fail_rate_by_provider.rename(columns={"sum": "n_success", "count": "n_total"})
fail_rate_by_provider = fail_rate_by_provider.sort_values("success_rate", ascending=False)
fail_rate_by_provider""")

md("### Figure: success rate by provider")
code("""fig, ax = plt.subplots(figsize=(5, 3.2))
order = fail_rate_by_provider.index.tolist()
rates = fail_rate_by_provider["success_rate"] * 100
bars = ax.bar(order, rates, color="#4C72B0")
for bar, (n_ok, n_tot) in zip(bars, zip(fail_rate_by_provider["n_success"], fail_rate_by_provider["n_total"])):
    ax.text(bar.get_x() + bar.get_width()/2, bar.get_height() + 1.5, f"{int(n_ok)}/{int(n_tot)}",
            ha="center", va="bottom", fontsize=8)
ax.set_ylabel("Run success rate (%)")
ax.set_ylim(0, 108)
ax.set_title("Run success rate by provider")
plt.tight_layout()
plt.savefig(FIGURES_DIR / "success_rate_by_provider.pdf")
plt.savefig(FIGURES_DIR / "success_rate_by_provider.png")
plt.show()""")

md("### Figure: cost per successful run by provider")
code("""cost_df = runs[(runs["success"] == True) & runs["estimated_cost_usd"].notna()]
cost_by_provider = cost_df.groupby("provider")["estimated_cost_usd"].agg(["mean", "sum", "count"])
cost_by_provider = cost_by_provider.sort_values("mean")
print(cost_by_provider)

fig, ax = plt.subplots(figsize=(5, 3.2))
ax.bar(cost_by_provider.index, cost_by_provider["mean"] * 100, color="#55A868")
ax.set_ylabel("Mean cost per run (cents USD)")
ax.set_title("Mean estimated cost per successful run")
plt.tight_layout()
plt.savefig(FIGURES_DIR / "cost_by_provider.pdf")
plt.savefig(FIGURES_DIR / "cost_by_provider.png")
plt.show()""")

# ============================================================ Grading
md("""## Grade factual answers against ground truth

17 question/thread-turns are gradable as factual (Q1-Q14 + Thread A's two turns
+ Thread B's first turn -- Thread B's second turn is a recommendation with no
single right answer despite sitting in question_list.md's "Quantitative"
section, so it's graded qualitatively below alongside Q15 and Thread C).

Ground-truth facts referenced below come from the corresponding cells in
`ground_truth_answers.ipynb`, corrected during this analysis where the first
pass turned out to test something the deployed agents structurally can't see
(see Q1, Q7, Q13 comments).""")

code("""def has_any(text, *needles):
    t = text.lower()
    return any(n.lower() in t for n in needles)

# ---- graders that only need output_text ----

def grade_Q1(t):
    # GT = the TOOL-REACHABLE universe by default, not the full 1341-establishment
    # SLCHD crosswalk. search_establishments (app/tools.py) queries FROM
    # establishments (Google-Local table) -- only 139/1341 SLCHD establishments
    # have a row there. Brighton Molly Green (the true county-wide #1) has ZERO
    # rows in establishments -- invisible to search_establishments specifically.
    # Naming it is graded "incorrect" BY DEFAULT here, then overridden to
    # "correct" case-by-case via MANUAL_OVERRIDES below if (and only if) the
    # run's own trace shows a supporting run_sql query against the broader
    # establishment_keys/inspections/violations chain -- i.e. a legitimately
    # evidenced answer, not a hallucination. Exactly one run in the dataset
    # names it, and its trace does contain that supporting query (see override).
    # Within the tool-reachable universe: Stella Grill tops by total (123/38),
    # Sagato Bakery & Cafe tops by critical (47/88).
    if has_any(t, "brighton molly green"):
        return "incorrect", "names Brighton Molly Green -- 0 rows in `establishments`; correct only if the run's own trace shows a supporting broad run_sql query (see MANUAL_OVERRIDES)"
    if has_any(t, "stella grill", "sagato"):
        return "correct", "names Stella Grill (top by total) or Sagato Bakery & Cafe (top by critical)"
    return "incorrect", "names neither tool-reachable top establishment"

def grade_Q2(t):
    weak = has_any(t, "weak", "no significant", "not significant", "little correlation",
                    "no meaningful", "no strong", "negligible", "near zero", "near-zero",
                    "no clear correlation", "no clear relationship", "not clearly correlated",
                    "tend to have fewer violations", "fewer violations")
    nums = re.findall(r"-?0?\\.\\d{1,3}", t)
    plausible_num = any(-0.5 <= float(n) <= 0.2 for n in nums if n not in (".", "-."))
    strong_claim = has_any(t, "strong correlation", "strongly correlated", "significant positive correlation",
                            "significant negative correlation", "clear positive correlation", "clear negative correlation")
    if strong_claim:
        return "incorrect", "claims a strong/significant correlation; GT is weak/near-zero (r=-0.25/-0.10)"
    if weak or plausible_num:
        return "correct", "states weak/near-zero correlation, negative direction, or a plausible r value"
    return "incorrect", "does not address the correlation question"

def grade_Q3(t):
    if has_any(t, "red iguana") and has_any(t, "no matched", "no inspection", "no violation history",
                                             "no record", "not in the", "no county", "does not have",
                                             "doesn't have", "no slchd", "not inspected", "no health inspection"):
        return "correct", "names Red Iguana and admits no inspection history"
    return "incorrect", "does not name Red Iguana + admit missing history"

def grade_Q4(t):
    return ("correct", "names Texas Roadhouse") if has_any(t, "texas roadhouse") else \\
           ("incorrect", "does not name Texas Roadhouse")

def grade_Q5(t):
    if has_any(t, "point") and has_any(t, "lower", "higher", "0 is clean", "0 =", "zero means", "clean"):
        return "correct", "explains points + clean/direction semantics"
    return "incorrect", "no clear points+direction explanation"

def grade_Q6(t):
    # GT: critical = Priority/Priority Foundation item (direct hazard control,
    # e.g. temperature/handwashing), non-critical = Core item (general
    # sanitation); critical citations average a HIGHER inspection score
    # (21.6 vs 15.9). Graded on whether the severity distinction is explained
    # correctly, not on whether score-effect is phrased in exact keywords.
    if has_any(t, "priority item", "priority foundation", "core item") or \\
       has_any(t, "more severe", "higher risk", "direct", "foodborne illness", "hazard", "immediate"):
        return "correct", "explains the critical/non-critical severity distinction correctly"
    return "incorrect", "no clear critical/non-critical distinction found"

def grade_Q7(t):
    # GT: 4 of 11 In-N-Out locations DO have real matched SLCHD histories (scores
    # 0-14); 7 don't. The well-supported answer discusses the real per-location
    # data, not a blanket "no data" claim (my first-pass assumption for this
    # grader was wrong in the other direction -- corrected after finding every
    # single successful run actually surfaced real matched data here).
    nums = [int(n) for n in re.findall(r"\\b(\\d{1,2})\\b", t)]
    plausible = any(0 <= n <= 20 for n in nums)
    mentions_locations = has_any(t, "west valley", "midvale", "riverton", "west jordan", "location")
    return ("correct", "discusses real per-location scores in plausible range") if (plausible and mentions_locations) else \\
           ("incorrect", "no plausible per-location score discussion")

def grade_Q8(t):
    # GT: score history is volatile (max 185 on 2023-07-13, caught by a Followup
    # the next day at 13); 9 of 10 inspections score above the countywide mean;
    # the LAST inspection (score 10) is near the county's best. A well-supported
    # answer flags both the historical spike/volatility AND the recent-good
    # trend -- reporting totals alone, or asserting a recent INCREASE (which
    # contradicts the data), are graded incorrect.
    mentions_spike = has_any(t, "185", "spike", "high score", "highest score", "worst inspection", "elevated")
    mentions_recent_ok = has_any(t, "improv", "declin", "recent", "trend", "getting better", "lower recently")
    claims_recent_increase = has_any(t, "recent increase", "increasing", "worsening trend")
    if claims_recent_increase and not mentions_spike:
        return "incorrect", "claims a recent increase -- contradicts GT (most recent score is near the county's best)"
    if mentions_spike and mentions_recent_ok:
        return "correct", "flags the historical spike/volatility AND the recent-trend direction"
    return "incorrect", "gives totals/chart only, no trend or fluctuation discussion"

def grade_Q9(t):
    return ("correct", "references cold-holding temperature/food-safety concept") if \\
           has_any(t, "41", "45", "temperature", "cold", "bacteria", "danger zone", "refrigerat") else \\
           ("incorrect", "no clear temperature/food-safety language found")

def grade_Q13(t):
    # GT: street_of() (used elsewhere) keeps the house number, so the literal
    # avg_rating==3.0 reading degenerates into a 78-way tie at 1 each -- not
    # informative. base_street() strips the house number and groups by
    # (base_street, city); under that grouping there's a genuine near-tie at the
    # top (State St/Sandy and State St/Murray both at 3 for the exact reading;
    # State St/Sandy leads the banded reading at 9), so graded generously against
    # the combined top-10 contenders from both readings.
    top_streets = ["state st", "main st", "redwood rd", "3900 s", "5600 w",
                   "12300 s", "2100 s", "harrison blvd", "north temple"]
    if has_any(t, *top_streets):
        return "correct", "names one of the GT top-10 (base_street, city) contenders"
    return "incorrect", "names a street inconsistent with the GT top contenders, or claims a degenerate/false result"

def grade_Q14(t):
    korean_higher = has_any(t, "korean") and has_any(t, "higher rat", "higher average", "korean has the higher",
                             "korean is higher", "korean edges", "korean slightly higher", "4.5", "4.6")
    admits_no_violation_data = has_any(t, "no violation", "0 violation", "zero violation", "no matched",
                                        "no inspection", "no data", "neither", "none of")
    return ("correct", "Korean higher rating + admits no violation data for either") if \\
           (korean_higher and admits_no_violation_data) else \\
           ("incorrect", "does not state Korean's higher rating + no-violation-data caveat together")

def grade_ThreadA_T1(t):
    return ("correct", "states 139 or 1.6%") if has_any(t, "139", "1.6%", "1.6 %") else \\
           ("incorrect", "does not state 139/1.6%")

def grade_ThreadB_T1(t):
    hi, mr = has_any(t, "red lotus"), has_any(t, "king buffet")
    if hi and mr:
        return "correct", "names both Red Lotus Bistro (highest-rated) and King Buffet (most-reviewed)"
    return "incorrect", "does not name both GT establishments"

# ---- graders that also need chart_image_files ----

def grade_Q10(row):
    t = row["output_text"]
    has_chart = len(row["chart_image_files"]) > 0
    nums = [int(n) for n in re.findall(r"\\b(\\d{2,3})\\b", t)]
    plausible_count = any(80 <= n <= 160 for n in nums)  # GT = 123
    if has_chart and (plausible_count or has_any(t, "critical violation")):
        return "correct", "produced a map and a plausible/relevant count"
    return "incorrect", "no chart, or no plausible count, for an explicit map request"

def grade_Q11(row):
    t = row["output_text"]
    has_chart = len(row["chart_image_files"]) > 0
    nums = re.findall(r"\\b\\d{1,2}\\.\\d\\b", t)
    plausible_mean = any(6.0 <= float(n) <= 16.0 for n in nums)  # GT mean ~10.3 (all) or ~12.4 (matched-only)
    if has_chart and plausible_mean:
        return "correct", "chart + plausible mean in range"
    return "incorrect", "no chart, or no plausible mean, for an explicit 'detailed visual analytics' request"

def grade_Q12(row):
    t = row["output_text"]
    has_chart = len(row["chart_image_files"]) > 0
    has_examples = bool(re.search(r"[A-Z][a-zA-Z''&\\.\\- ]{3,40}", t)) and has_any(t, "increas", "decreas", "improv", "worsen")
    if has_chart and has_examples:
        return "correct", "chart + named increase/decrease examples"
    return "incorrect", "missing chart or named examples for an explicit visual-analysis request"

def grade_ThreadA_T2(row):
    has_chart = len(row["chart_image_files"]) > 0
    return ("correct", "chart produced for distribution/timeline request") if has_chart else \\
           ("incorrect", "no chart for an explicit distribution/timeline request")

GRADERS_TEXT = {
    "Q1": grade_Q1, "Q2": grade_Q2, "Q3": grade_Q3, "Q4": grade_Q4, "Q5": grade_Q5,
    "Q6": grade_Q6, "Q7": grade_Q7, "Q8": grade_Q8, "Q9": grade_Q9, "Q13": grade_Q13,
    "Q14": grade_Q14, "ThreadA_T1": grade_ThreadA_T1, "ThreadB_T1": grade_ThreadB_T1,
}
GRADERS_ROW = {"Q10": grade_Q10, "Q11": grade_Q11, "Q12": grade_Q12, "ThreadA_T2": grade_ThreadA_T2}
FACTUAL_QIDS = set(GRADERS_TEXT) | set(GRADERS_ROW)

succ = runs[(runs["success"] == True) & (runs["qid"].isin(FACTUAL_QIDS))].copy()
verdicts, reasons = [], []
for _, row in succ.iterrows():
    grader = GRADERS_TEXT.get(row["qid"]) or GRADERS_ROW.get(row["qid"])
    v, r = grader(row["output_text"]) if row["qid"] in GRADERS_TEXT else grader(row)
    verdicts.append(v); reasons.append(r)
succ["verdict"] = verdicts
succ["reason"] = reasons
print(f"{len(succ)} successful factual runs graded by rule")
succ.groupby(["qid", "verdict"]).size().unstack(fill_value=0)""")

md("""### Manual review

Every case the automated rules couldn't resolve on the first pass (29 of 184,
16%) was read in full -- output text and, where relevant, tool-call trace --
and hand-labeled. Three of these overturned a wrong assumption in the
automated rule itself rather than just resolving an ambiguous case (Q1's
tool-reachability, Q7's real per-location data, Q13's street-grouping
granularity) -- those fixes are already baked into the graders above, so this
override list is what's left: individual runs whose specific wording the
keyword rules couldn't parse.""")
code("""MANUAL_OVERRIDES = {
    ("Q6", "openai", "v2_memory"): ("correct", "manual: correctly explains Priority/Core distinction"),
    ("Q6", "groq", "v3_memory"): ("correct", "manual: correctly explains critical=higher risk"),
    ("Q6", "groq", "v2_memory"): ("correct", "manual: correctly explains Priority/Priority Foundation/Core"),
    ("Q6", "anthropic", "v1_memory"): ("correct", "manual: correctly cites violation_codes.critical + definitions"),
    ("Q6", "anthropic", "v2_memory"): ("correct", "manual: correctly cites R392-100 Priority Item tiers"),
    ("Q5", "openai", "v3_memory"): ("correct", "manual: correctly explains score semantics"),
    ("Q5", "openai", "v2_memory"): ("correct", "manual: explicitly states 0=clean, higher=worse"),
    ("Q5", "groq", "v3_memory"): ("correct", "manual: correct direction (higher=worse)"),
    ("Q2", "groq", "v3_memory"): ("correct", "manual: correct direction (higher rating -> fewer violations), no overclaim"),
    ("Q14", "groq", "v3_memory"): ("correct", "manual: Korean 4.59 > Thai 4.46, both 0 violations -- matches GT"),
    ("Q14", "google", "v2_memory"): ("correct", "manual: states Korean has higher average rating, matches GT"),
    ("Q11", "groq", "v2_memory"): ("correct", "manual: numbers match GT exactly (7798/10.29/297/0) despite 'establishments' mislabel"),
    ("Q1", "groq", "v3_memory"): ("incorrect", "manual: 'Panda Express 337 violations' -- fabricated, matches no valid reading"),
    ("Q1", "google", "v1_memory"): ("correct", "manual: names Brighton Molly Green (250 total/114 critical). Verified NOT a hallucination -- "
                                    "full trace shows search_establishments returned Stella Grill first, the agent then wrote a "
                                    "run_sql query directly against establishment_keys/inspections/violations (the broader, "
                                    "non-Google-matched universe) after a get_schema call, and that query legitimately returned "
                                    "Brighton Molly Green at 250/114, matching the county-wide ground truth exactly. The agent did "
                                    "more work than search_establishments alone provides and reported it faithfully; grading this "
                                    "as a hallucination (an earlier pass in this analysis did) was an error from not reading far "
                                    "enough into the trace."),
    ("ThreadB_T1", "anthropic", "v2_memory"): ("incorrect", "manual: misses Red Lotus Bistro, which beats its picks on both the rating tie and review count"),
    ("Q8", "groq", "v2_memory"): ("incorrect", "manual: gives totals only, admits it lacks inspection history -- no trend answer"),
    ("Q8", "groq", "v1_memory"): ("incorrect", "manual: gives totals only, no trend/fluctuation discussion at all"),
    ("Q8", "groq", "v3_memory"): ("incorrect", "manual: claims 'recent increase' in critical violations -- contradicts GT"),
    ("Q2", "groq", "v1_memory"): ("incorrect", "manual: lists top-50 by rating, never addresses correlation with violations"),
    ("Q12", "ollama", "v3_memory"): ("incorrect", "manual: no chart produced for an explicit visual-analysis request"),
    ("Q12", "ollama", "v2_memory"): ("incorrect", "manual: output_text is empty despite success=True"),
    ("Q12", "ollama", "v1_memory"): ("incorrect", "manual: no chart produced for an explicit visual-analysis request"),
    ("Q12", "groq", "v1_memory"): ("incorrect", "manual: answers a different question entirely (most/least-reviewed restaurants)"),
    ("Q12", "groq", "v3_memory"): ("incorrect", "manual: explicitly states it cannot provide the requested visual analysis"),
    ("Q11", "groq", "v3_memory"): ("incorrect", "manual: claims score range 0-49 -- contradicts GT (true range 0-297)"),
    ("Q11", "groq", "v1_memory"): ("incorrect", "manual: answers a different question entirely (rating distribution, not inspection scores)"),
    ("Q13", "ollama", "v2_memory"): ("incorrect", "manual: reports the degenerate literal-tie finding without surfacing a useful answer"),
    ("Q13", "groq", "v2_memory"): ("incorrect", "manual: misreads a single top row as 'the count', not an actual per-street tally"),
    ("Q13", "groq", "v3_memory"): ("incorrect", "manual: claims only one 3.0-rated restaurant exists -- contradicts GT (78 establishments)"),
    ("Q7", "groq", "v3_memory"): ("incorrect", "manual: output is a broken/leaked internal string, not a real answer"),
    # --- Ollama Q1-Q10 + Thread A/B (runs moved into ollama_runs/ 2026-09-29) ---
    # Only the runs the rules can't settle on their own, by the same standard used for the other providers:
    # the rule itself defers to a trace check (Q1), its keyword check has already misfired on correct answers
    # for other providers (Q5), or the output is anomalous in a way the rule doesn't look at (Q10).
    # The other 35 new Ollama verdicts stand as rule-graded -- incl. the three empty answers (Q2 V2, Q4 V1,
    # Q7 V2 -> incorrect) and Thread A T1 "1,315" (-> incorrect, same as openai V1/V2's identical answer).
    ("Q1", "ollama", "v2_memory"): ("correct", "manual: names Brighton Molly Green (250). Same pattern as Q1 google v1 -- search_establishments "
                                   "returned Stella Grill first; after two failed plot_chart calls and a get_schema, its own run_sql over "
                                   "establishment_keys/inspections/violations (grouped per location) returned Brighton Molly Green 250, "
                                   "Cafe Rio 164, Teriyaki Grill 126 -- all reported faithfully"),
    ("Q5", "ollama", "v1_memory"): ("correct", "manual: 'A lower score is better', 0 = clean, higher = more/more severe violations -- "
                                   "correct direction; rule missed it only for lacking the word 'point'"),
    ("Q5", "ollama", "v2_memory"): ("correct", "manual: 'A lower score is better', 0 = clean, higher = more/more severe violations, plus "
                                   "Priority/Priority Foundation/Core tiers -- correct direction; rule missed it only for lacking 'point'"),
    ("Q10", "ollama", "v2_memory"): ("correct", "manual: real answer present -- map of critical-violation restaurants, names Sagato (47) / "
                                    "Stella Grill (38), 98.4% caveat -- followed by ~22k chars of raw search_establishments JSON pasted "
                                    "into the reply: a presentation defect, not a wrong answer (unlike Q7 groq v3, which had no answer). "
                                    "'50 restaurants' is the tool's default limit, same wording as ollama v1 (rule-graded correct)"),
}
for idx, row in succ.iterrows():
    key = (row["qid"], row["provider"], row["variant"])
    if key in MANUAL_OVERRIDES:
        v, r = MANUAL_OVERRIDES[key]
        succ.at[idx, "verdict"] = v
        succ.at[idx, "reason"] = r
print(f"applied {len(MANUAL_OVERRIDES)} manual overrides")
succ.groupby(["qid", "verdict"]).size().unstack(fill_value=0)""")

# ============================================================ Results table
md("""## Results table: question x provider

Each cell is `n_correct/n_attempted` -- attempted = successful runs only
(failures are handled separately above, not folded into "incorrect" here, so
this table answers "of the times each system actually responded, how often
was it right").""")
code("""QUESTION_ORDER = ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "Q8", "Q9", "Q10",
                  "Q11", "Q12", "Q13", "Q14", "ThreadA_T1", "ThreadA_T2", "ThreadB_T1"]
PROVIDER_ORDER = ["anthropic", "google", "groq", "openai", "ollama"]
PROVIDER_LABEL = {"anthropic": "Claude", "google": "Gemini", "groq": "Llama 3.3 (Groq)",
                   "openai": "GPT", "ollama": "Ollama (local)"}

succ["is_correct"] = (succ["verdict"] == "correct").astype(int)
grid_n = succ.pivot_table(index="qid", columns="provider", values="is_correct", aggfunc="count")
grid_correct = succ.pivot_table(index="qid", columns="provider", values="is_correct", aggfunc="sum")
grid_frac = (grid_correct / grid_n).reindex(index=QUESTION_ORDER, columns=PROVIDER_ORDER)

grid_display = pd.DataFrame(index=QUESTION_ORDER, columns=PROVIDER_ORDER, dtype=object)
for qid in QUESTION_ORDER:
    for prov in PROVIDER_ORDER:
        n = grid_n.loc[qid, prov] if (qid in grid_n.index and prov in grid_n.columns and pd.notna(grid_n.loc[qid, prov])) else 0
        c = grid_correct.loc[qid, prov] if (qid in grid_correct.index and prov in grid_correct.columns and pd.notna(grid_correct.loc[qid, prov])) else 0
        grid_display.loc[qid, prov] = f"{int(c)}/{int(n)}" if n else "--"
grid_display.columns = [PROVIDER_LABEL[p] for p in PROVIDER_ORDER]
grid_display""")

md("### Figure: accuracy heatmap")
code("""fig, ax = plt.subplots(figsize=(6.5, 6))
data = grid_frac.values.astype(float)
im = ax.imshow(data, cmap="RdYlGn", vmin=0, vmax=1, aspect="auto")
ax.set_xticks(range(len(PROVIDER_ORDER)))
ax.set_xticklabels([PROVIDER_LABEL[p] for p in PROVIDER_ORDER], rotation=30, ha="right")
ax.set_yticks(range(len(QUESTION_ORDER)))
ax.set_yticklabels(QUESTION_ORDER)
for i in range(len(QUESTION_ORDER)):
    for j in range(len(PROVIDER_ORDER)):
        qid, prov = QUESTION_ORDER[i], PROVIDER_ORDER[j]
        label = grid_display.loc[qid, PROVIDER_LABEL[prov]]
        if label != "--":
            ax.text(j, i, label, ha="center", va="center", fontsize=7)
ax.set_title("Fraction correct by question x provider\\n(across V1/V2/V3 grounding variants)")
fig.colorbar(im, ax=ax, label="Fraction correct", shrink=0.7)
plt.tight_layout()
plt.savefig(FIGURES_DIR / "accuracy_heatmap.pdf")
plt.savefig(FIGURES_DIR / "accuracy_heatmap.png")
plt.show()""")

md("### Overall accuracy per provider (across all 17 factual questions)")
code("""overall = succ.groupby("provider")["is_correct"].agg(["sum", "count"])
overall["accuracy"] = overall["sum"] / overall["count"]
overall = overall.reindex(PROVIDER_ORDER).rename(columns={"sum": "n_correct", "count": "n_attempted"})
overall.index = [PROVIDER_LABEL[p] for p in overall.index]
overall""")

# ============================================================ Qualitative examples
md("""## Qualitative examples: best / worst per question

4 qualitative question-instances (Q15, Thread B turn 2, Thread C turns 1-2 --
Thread B turn 2 is regrouped here from question_list.md's "Quantitative"
heading since it's an open-ended recommendation with no single right answer,
same as `ground_truth_answers.ipynb` itself notes). One best + one worst example
selected per question, read in full and picked against the rubric: best =
accurate facts, sensible visualization/reasoning, admits missing data, offers
alternatives; worst = incorrect facts, no visualization, no evidence/reasoning.

A clear pattern emerged across all 4: Google/Gemini produced the best-rubric
answer every time (long, well-grounded, explicit about data gaps, multiple
ranked alternatives); Groq produced the worst in 3 of 4 (including one answer
that is a literal unfilled template placeholder).""")
code("""QUALITATIVE_QIDS = ["Q15", "ThreadB_T2", "ThreadC_T1", "ThreadC_T2"]
QUALITATIVE_PICKS = {
    "Q15": {
        "best": ("google", "v1_memory", "Names 5 savory (non-sweet) options in Rose Park + 3 nearby, "
                 "reasons about 'savory' via cuisine type since the data has no sweet/savory flag, "
                 "states SLCHD match status per establishment (admits missing data honestly), and "
                 "closes with the dataset-wide 98.4% unmatched-rate caveat."),
        "worst": ("groq", "v3_memory", "Output contains a literal unfilled template placeholder: "
                  "'[insert name of top-rated establishment]' -- never substituted with a real name."),
    },
    "ThreadB_T2": {
        "best": ("google", "v2_memory", "Surfaces 4 real candidates (not just the 2 from turn 1) with "
                 "a recommendation matrix keyed to different priorities (quality/volume/value/variety), "
                 "each with real rating+review numbers, plus the no-SLCHD-data caveat."),
        "worst": ("groq", "v3_memory", "One sentence recommending a restaurant that was never one of the "
                  "two candidates established in turn 1 -- ignores the conversation's own prior turn."),
    },
    "ThreadC_T1": {
        "best": ("google", "v2_memory", "Quantifies halal options (70/8592, ~1.2%), breaks down by "
                 "geography, cuisine, rating, and price tier, cites the regulatory context (R392-100 "
                 "'Honestly Presented'), and flags the 69/70 unmatched-SLCHD caveat explicitly."),
        "worst": ("groq", "v3_memory", "Vague non-answer ('only a few establishments') -- never states a "
                  "number despite having tools that could compute one; no chart."),
    },
    "ThreadC_T2": {
        "best": ("google", "v2_memory", "Recommends specific vegetable-forward dishes across 3 cuisine "
                 "groupings with real establishments/ratings/reviews and specific menu items, plus the "
                 "missing-inspection-data caveat."),
        "worst": ("groq", "v1_memory", "Flatly false single-sentence claim: 'There are no vegetarian "
                  "restaurants in Salt Lake County' -- contradicts the data (86 halal-tagged "
                  "establishments alone also carry a Vegetarian options attribute)."),
    },
}

for qid, picks in QUALITATIVE_PICKS.items():
    print(f"=== {qid} ===")
    for label, (provider, variant, justification) in picks.items():
        row = runs[(runs["qid"] == qid) & (runs["provider"] == provider) & (runs["variant"] == variant)].iloc[0]
        print(f"[{label.upper()}] {provider}/{variant}")
        print(f"  why: {justification}")
        # Copy this run's chart(s) into figures/qualitative_examples/ with a
        # predictable name so results_section.tex can \\includegraphics them directly.
        src_dir = Path(row["path"]).parent
        for i, fname in enumerate(row["chart_image_files"]):
            src = src_dir / fname
            if src.exists():
                dst = FIGURES_DIR / "qualitative_examples" / f"{qid}_{label}_{provider}_chart{i}.png"
                shutil.copy(src, dst)
                print(f"  copied chart -> {dst.relative_to(ROOT)}")
    print()""")

# ============================================================ Export
md("## Export summary numbers for results_section.tex")
code("""summary = {
    "n_total_runs": int(len(runs)),
    "n_success": int((runs["success"] == True).sum()),
    "n_failed": int((runs["success"] == False).sum()),
    "providers": PROVIDER_ORDER,
    "success_rate_by_provider": fail_rate_by_provider["success_rate"].round(3).to_dict(),
    "counts_by_provider": {p: {"n_success": int(fail_rate_by_provider.loc[p, "n_success"]),
                                "n_total": int(fail_rate_by_provider.loc[p, "n_total"])}
                           for p in fail_rate_by_provider.index},
    "failure_categories": failure_summary.to_dict("records"),
    "overall_accuracy_by_provider": overall["accuracy"].round(3).to_dict(),
    "grid_display": grid_display.to_dict("index"),
    "n_factual_questions": len(QUESTION_ORDER),
    "n_qualitative_questions": len(QUALITATIVE_QIDS),
    "n_manual_overrides": len(MANUAL_OVERRIDES),
    "n_uncertain_after_review": int((succ["verdict"] == "uncertain").sum()),
}
with open(ROOT / "results_summary.json", "w") as f:
    json.dump(summary, f, indent=2, default=str)
print("wrote results_summary.json")
print(json.dumps(summary, indent=2, default=str)[:2000])""")

nb["cells"] = cells
from pathlib import Path as _Path
nbf.write(nb, _Path(__file__).resolve().parent.parent / "results_analysis.ipynb")
print(f"wrote results_analysis.ipynb with {len(cells)} cells")
