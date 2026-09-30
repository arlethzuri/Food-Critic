"""Builds and executes ground_truth_answers.ipynb at the project root.

Computes verified answers to every question in question_list.md directly
from db/food_health.duckdb (plus semantic/ and the RAG index for definitional
questions), for grading the agentic system's answers against.

Source of truth: this script. Hand-editing the generated .ipynb won't
persist -- change a cell here and rerun instead.

  .venv/bin/python scripts/build_ground_truth_notebook.py
  .venv/bin/jupyter nbconvert --to notebook --execute --inplace ground_truth_answers.ipynb
"""
from pathlib import Path

import nbformat as nbf
from nbformat.v4 import new_notebook, new_code_cell, new_markdown_cell

ROOT = Path(__file__).resolve().parent.parent
nb = new_notebook()
cells = []

def md(text):
    cells.append(new_markdown_cell(text))

def code(text):
    cells.append(new_code_cell(text))

# ============================================================ Header
md("""# Ground truth answers

Computed, verifiable answers to every question in `question_list.md`, for evaluating the agentic system's answers against — not the agent's own claims about itself.

**How to read this notebook:**
- **Factual/quantitative questions** get a directly computed answer from `db/food_health.duckdb`.
- **Definitional questions** ("what does X mean") are answered from `semantic/data_dictionary.json` (this project's own verified column semantics) plus the actual regulation text, retrieved live from the same RAG index the agents themselves query (`app/rag/retriever.py`) — so the citation is exactly what a correct agent answer should also be citing.
- **Qualitative/recommendation questions** ("which do you recommend") **do not have one correct answer** — there's no ground truth for taste. For these, this notebook computes the *grounding facts* a reasonable answer must be consistent with (the actual candidates, their real ratings/reviews/violations), so you can judge whether the agent's recommendation is well-supported by the data it had access to, not whether it matches a single "right" restaurant.

Read-only connection — this notebook cannot modify the database.""")

code("""import json
import re
from pathlib import Path

import duckdb
import pandas as pd
import plotly.express as px

ROOT = Path(".").resolve()
DB_PATH = ROOT / "db" / "food_health.duckdb"
DATA_DICTIONARY = json.loads((ROOT / "semantic" / "data_dictionary.json").read_text(encoding="utf-8"))
VIOLATION_MAP = pd.read_csv(ROOT / "semantic" / "violation_map.csv")

con = duckdb.connect(str(DB_PATH), read_only=True)
con.execute("INSTALL spatial; LOAD spatial;")


def q(sql: str, params=None) -> pd.DataFrame:
    return (con.execute(sql, params) if params is not None else con.execute(sql)).fetchdf()


def glossary(table_dot_column: str) -> None:
    entry = DATA_DICTIONARY["columns"].get(table_dot_column)
    print(json.dumps(entry, indent=2) if entry else f"No glossary entry for {table_dot_column!r}")


def address_preview(name: str, address) -> str:
    if not isinstance(address, str) or not address:
        return ""
    prefix = f"{name}, "
    return address[len(prefix):] if address.lower().startswith(prefix.lower()) else address


def street_of(name: str, address: str) -> str:
    preview = address_preview(name, address)
    return preview.split(",")[0].strip() if preview else ""


def base_street(name: str, address) -> str:
    seg = street_of(name, address)
    if not seg:
        return ""
    seg = re.sub(r"\\s*#\\S+", "", seg)  # drop unit/suite suffix, e.g. "State St #1310"
    seg = re.sub(r"^\\d+\\S*\\s+", "", seg)  # drop the leading house-number token
    return seg.strip()


def city_of(address) -> str:
    if not isinstance(address, str) or not address:
        return ""
    parts = address.split(",")
    return parts[-2].strip() if len(parts) >= 2 else ""
""")

code("""import sys
sys.path.insert(0, "app")
from rag.retriever import load_retriever

retriever = load_retriever(k=3)


def regulation_excerpt(query: str) -> None:
    for d in retriever.invoke(query):
        meta = d.metadata
        loc = meta.get("source", "unknown") + (f", p.{meta['page']}" if meta.get("page") else "")
        print(f"[{loc}]")
        print(d.page_content.strip()[:600])
        print()
""")

# ============================================================ Section 1
md("## No-checkpoint / no-memory questions — Quantitative")

md("### Q1. Which restaurant/restaurants violated health/food codes most?")
code("""violations_per_establishment = q(\"\"\"
    SELECT ek.name, ek.slchd_establishment_key,
           COUNT(*) FILTER (WHERE vc.critical) AS critical_violations,
           COUNT(*) AS total_violations
    FROM establishment_keys ek
    JOIN inspections i ON i.slchd_establishment_key = ek.slchd_establishment_key
    JOIN violations v ON v.inspection_id = i.inspection_id
    JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
    GROUP BY ek.name, ek.slchd_establishment_key
\"\"\")
print("Top 10 by TOTAL violations:")
display(violations_per_establishment.sort_values("total_violations", ascending=False).head(10))
print("\\nTop 10 by CRITICAL violations (the more safety-relevant ranking):")
display(violations_per_establishment.sort_values("critical_violations", ascending=False).head(10))""")

md("""#### Q1 (alternate). Same ranking, with duplicate inspection records de-duped

The query above takes `inspections`/`violations` at face value, but the raw scrape
has two known duplication patterns that inflate counts if left unhandled (see
`semantic/ontology.json`'s `duplicate_scrape_violations` flag, plus a second
pattern found by direct inspection of `db/food_health.duckdb`):

1. **Duplicate inspection *events*** (undocumented in the ontology): 16 groups
   where the same establishment has two different `inspection_id` values for the
   same `(inspection_date, inspection_type_id)` — the same real-world inspection
   scraped twice. Verified directly: in all 16 groups both `inspection_id`s carry
   byte-identical violation-code sets, confirming they're the same inspection, not
   two genuine visits. `BRIGHTON MOLLY GREEN` (inspection_id 520/521) is one of
   these, and was previously the #1-ranked establishment above almost entirely as
   an artifact of this bug.
2. **Duplicate violation *citations* within one inspection** (documented flag):
   480 `(inspection_id, violation_code_id)` pairs are cited more than once inside
   a single inspection (OCR/scrape artifact), affecting 173 inspections.""")
code("""violations_per_establishment_deduped = q(\"\"\"
    WITH deduped_inspections AS (
        SELECT slchd_establishment_key, MIN(inspection_id) AS inspection_id
        FROM inspections
        GROUP BY slchd_establishment_key, inspection_date, inspection_type_id
    ),
    distinct_citations AS (
        SELECT DISTINCT v.inspection_id, v.violation_code_id
        FROM violations v
        JOIN deduped_inspections di ON di.inspection_id = v.inspection_id
    )
    SELECT ek.name, ek.slchd_establishment_key,
           COUNT(*) FILTER (WHERE vc.critical) AS critical_violations,
           COUNT(*) AS total_violations
    FROM establishment_keys ek
    JOIN deduped_inspections di ON di.slchd_establishment_key = ek.slchd_establishment_key
    JOIN distinct_citations dc ON dc.inspection_id = di.inspection_id
    JOIN violation_codes vc ON vc.violation_code_id = dc.violation_code_id
    GROUP BY ek.name, ek.slchd_establishment_key
\"\"\")
print("De-duped -- Top 10 by TOTAL violations:")
display(violations_per_establishment_deduped.sort_values("total_violations", ascending=False).head(10))
print("\\nDe-duped -- Top 10 by CRITICAL violations:")
display(violations_per_establishment_deduped.sort_values("critical_violations", ascending=False).head(10))""")

md("""#### Q1 (as reachable via the deployed system's tools) -- the operative ground truth for grading agent answers

**Neither version above is what the deployed agents can actually see.** Both use
`establishment_keys`, the broad SLCHD-side crosswalk (1,341 distinct establishments).
But the agents' only establishment-ranking tool, `search_establishments` in
`app/tools.py`, queries `FROM establishments e` -- the Google-Local table -- and
only 139 of those 1,341 SLCHD establishments have a matching row there (`e.slchd_establishment_key
IS NOT NULL`). `BRIGHTON MOLLY GREEN` (the #1 answer above) has **zero** rows in
`establishments`: it is structurally invisible to `search_establishments`, regardless
of how well the agent reasons. Confirmed directly against the actual system: a real
`google/v1_memory` run's own tool call returned Stella Grill as row 1 (123 total / 38
critical) -- yet that run's final answer text named Brighton Molly Green anyway, i.e.
the model contradicted its own retrieved evidence (see Q1 grading notes).

An agent *could* still reach the full 1,341-establishment universe via the separate
`run_sql` tool (unrestricted read-only SQL, per its docstring), but `search_establishments`'s
own docstring explicitly steers agents there for "most/worst violations" questions,
and none of the runs that did use `run_sql` for this question ended up reporting
Brighton Molly Green correctly either. So: **this is the fair ground truth to grade
agent answers against** -- not the county-wide numbers above, which the deployed
tools cannot surface. The gap itself (139/1,341 = 10.4% coverage) is a real finding
worth reporting on its own.""")
code("""violations_reachable = q(\"\"\"
    WITH deduped_inspections AS (
        SELECT slchd_establishment_key, MIN(inspection_id) AS inspection_id
        FROM inspections
        GROUP BY slchd_establishment_key, inspection_date, inspection_type_id
    ),
    distinct_citations AS (
        SELECT DISTINCT v.inspection_id, v.violation_code_id
        FROM violations v
        JOIN deduped_inspections di ON di.inspection_id = v.inspection_id
    )
    -- Same base table as search_establishments (FROM establishments e), not
    -- establishment_keys -- this is the actual universe the deployed tool ranks
    -- over. Undeduped variant (matching what the live tool returns today, since
    -- it has neither of Q1-alternate's fixes) is computed right after for the
    -- exact numbers a real agent would have seen.
    SELECT e.name, e.slchd_establishment_key,
           COUNT(*) FILTER (WHERE vc.critical) AS critical_violations,
           COUNT(*) AS total_violations
    FROM establishments e
    JOIN deduped_inspections di ON di.slchd_establishment_key = e.slchd_establishment_key
    JOIN distinct_citations dc ON dc.inspection_id = di.inspection_id
    JOIN violation_codes vc ON vc.violation_code_id = dc.violation_code_id
    GROUP BY e.name, e.slchd_establishment_key
\"\"\")
print(f\"{q('SELECT COUNT(*) AS n FROM establishments WHERE slchd_establishment_key IS NOT NULL').iloc[0]['n']} \"
      f\"of {q('SELECT COUNT(DISTINCT slchd_establishment_key) AS n FROM establishment_keys').iloc[0]['n']} \"
      \"SLCHD establishments are reachable via search_establishments (have a Google-Local match).\")
print(\"\\nTool-reachable, de-duped -- Top 10 by TOTAL violations:\")
display(violations_reachable.sort_values(\"total_violations\", ascending=False).head(10))
print(\"\\nTool-reachable, de-duped -- Top 10 by CRITICAL violations:\")
display(violations_reachable.sort_values(\"critical_violations\", ascending=False).head(10))

# Undeduped version -- what search_establishments actually returns today (its
# violation_join has neither of the two dedup fixes above) -- so THIS is the
# exact number set a real agent's tool observation would contain.
violations_reachable_raw = q(\"\"\"
    SELECT e.name, e.slchd_establishment_key,
           COUNT(*) FILTER (WHERE vc.critical) AS critical_violations,
           COUNT(*) AS total_violations
    FROM establishments e
    JOIN inspections i ON i.slchd_establishment_key = e.slchd_establishment_key
    JOIN violations v ON v.inspection_id = i.inspection_id
    JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
    GROUP BY e.name, e.slchd_establishment_key
\"\"\")
print(\"\\nTool-reachable, RAW (matches the live tool's actual output today) -- Top 5 by TOTAL:\")
display(violations_reachable_raw.sort_values(\"total_violations\", ascending=False).head(5))
print(\"\\nTool-reachable, RAW -- Top 5 by CRITICAL:\")
display(violations_reachable_raw.sort_values(\"critical_violations\", ascending=False).head(5))""")

md("### Q2. Is there any correlation between ratings and violations among the restaurants?")
code("""rating_vs_violations = q(\"\"\"
    SELECT e.name, e.avg_rating,
           COALESCE(vcount.critical_violation_count, 0) AS critical_violation_count,
           COALESCE(vcount.total_violation_count, 0) AS total_violation_count
    FROM establishments e
    JOIN establishment_keys ek ON ek.slchd_establishment_key = e.slchd_establishment_key
    LEFT JOIN (
        SELECT i.slchd_establishment_key,
               COUNT(*) FILTER (WHERE vc.critical) AS critical_violation_count,
               COUNT(*) AS total_violation_count
        FROM inspections i
        JOIN violations v ON v.inspection_id = i.inspection_id
        JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
        GROUP BY i.slchd_establishment_key
    ) vcount ON vcount.slchd_establishment_key = e.slchd_establishment_key
    WHERE e.avg_rating IS NOT NULL
\"\"\")
print(f"n = {len(rating_vs_violations)} establishments with both a rating and a matched SLCHD record")
print("Pearson correlation, avg_rating vs total_violation_count:",
      round(rating_vs_violations["avg_rating"].corr(rating_vs_violations["total_violation_count"]), 3))
print("Pearson correlation, avg_rating vs critical_violation_count:",
      round(rating_vs_violations["avg_rating"].corr(rating_vs_violations["critical_violation_count"]), 3))
print("(Near zero / weak correlation either way is itself the finding — worth stating explicitly, not implying a relationship that isn't there.)")""")

md("### Q3. Name of the restaurant with the most reviews, and its full violation history")
code("""top_reviewed = q("SELECT * FROM establishments ORDER BY num_of_reviews DESC LIMIT 1").iloc[0]
print(f"{top_reviewed['name']}  (num_of_reviews={top_reviewed['num_of_reviews']}, avg_rating={top_reviewed['avg_rating']})")
if pd.isna(top_reviewed["slchd_establishment_key"]) or not top_reviewed["slchd_establishment_key"]:
    print("No matched SLCHD inspection history — this establishment is in the 98.4% with no county inspection record.")
else:
    history = q(\"\"\"
        SELECT i.inspection_date, i.inspection_score, vc.code_text, vc.critical, v.violation_phr
        FROM inspections i
        LEFT JOIN violations v ON v.inspection_id = i.inspection_id
        LEFT JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
        WHERE i.slchd_establishment_key = ?
        ORDER BY i.inspection_date DESC
    \"\"\", [top_reviewed["slchd_establishment_key"]])
    display(history)""")

md("### Q4. Restaurant with the most reviews that has had a violation")
code("""most_reviewed_with_violation = q(\"\"\"
    SELECT DISTINCT e.name, e.num_of_reviews, e.avg_rating
    FROM establishments e
    JOIN inspections i ON i.slchd_establishment_key = e.slchd_establishment_key
    JOIN violations v ON v.inspection_id = i.inspection_id
    ORDER BY e.num_of_reviews DESC
    LIMIT 1
\"\"\")
display(most_reviewed_with_violation)""")

md("""### Q5. What does an inspection score mean?

From this project's verified data dictionary, plus the actual regulation text (same source the agents themselves retrieve from).""")
code("""glossary("inspections.inspection_score")
print()
regulation_excerpt("what does the inspection score mean, how is it calculated")""")

md("### Q6. Difference between critical and non-critical violations, and effect on inspection score")
code("""glossary("violation_codes.critical")
print()
glossary("violation_codes.asterisk_count")
print()
score_by_severity = q(\"\"\"
    SELECT vc.critical, AVG(i.inspection_score) AS avg_inspection_score, COUNT(DISTINCT i.inspection_id) AS n_inspections
    FROM inspections i
    JOIN violations v ON v.inspection_id = i.inspection_id
    JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
    GROUP BY vc.critical
\"\"\")
print("Average inspection_score for inspections citing a critical vs. non-critical violation:")
display(score_by_severity)
print()
print('=== "Priority Item" (source: R392-100 Food Service Sanitation Rule, p.17) ===')
print(\"\"\"Priority Item.

(1) "Priority item" also referred to as "critical 1" means a provision in the
Model Code whose application contributes directly to the elimination,
prevention or reduction to an acceptable level, hazards associated with food
borne illness or injury and there is no provision that more directly controls
the hazard.

(2) "Priority item" includes items with a quantifiable measure to show control
of hazards such as cooking, reheating, cooling, handwashing; and

(3) "Priority item" is an item that is denoted in this Code with a superscript
P-P.\"\"\")
print()
print('=== "Core Item" (source: R392-100 Food Service Sanitation Rule, p.6) ===')
print(\"\"\"Core Item.

(1) "Core item" also referred to as "non critical" means a provision in the
Model Code that is not designated as a Priority Item or a Priority Foundation
Item.

(2) "Core item" includes an item that usually relates to general sanitation,
operational controls, sanitation standard operating procedures (SSOPs),
facilities or structures, equipment design, or general maintenance.\"\"\")
print()
print(
    "How they differ, per the rule's own definitions: a Priority Item is defined "
    "positively -- it directly controls a foodborne-illness hazard (cooking, "
    "cooling, handwashing, etc.) and is marked with a superscript P in the code. "
    "A Core Item is defined negatively -- it is, by definition, whatever is left "
    "over once Priority Items and Priority Foundation Items are excluded, and "
    "covers general sanitation/maintenance/operational upkeep rather than a "
    "specific hazard-control action. Note the rule text actually has 3 tiers "
    "(Priority / Priority Foundation / Core, i.e. 'critical 1' / 'critical 2' / "
    "'non-critical'), while this dataset's violation_codes.critical column is a "
    "collapsed boolean -- it does not preserve the Priority vs. Priority "
    "Foundation distinction, only critical vs. non-critical."
)""")

md("""### Q7. Is the In-N-Out Burger a safe bet to eat at right now?

4 of the 11 In-N-Out locations DO have a matched SLCHD history (real scores, 0-14
range) -- the other 7 don't. A well-supported answer should use the real per-location
data where it exists and flag its absence where it doesn't, not blanket-claim no
data exists for the chain.""")
code("""in_n_out = q("SELECT * FROM establishments WHERE lower(name) LIKE '%in-n-out%' OR lower(name) LIKE '%in n out%'")
display(in_n_out[["name", "address", "avg_rating", "num_of_reviews", "slchd_establishment_key"]])
for _, row in in_n_out.iterrows():
    print(f"\\n--- {row['name']} ({row['address']}) ---")
    if pd.isna(row["slchd_establishment_key"]) or not row["slchd_establishment_key"]:
        print("No matched SLCHD inspection history — cannot assess safety from county data; a correct answer must say so explicitly, not imply a clean record.")
    else:
        display(q("SELECT inspection_date, inspection_score FROM inspections WHERE slchd_establishment_key = ? ORDER BY inspection_date DESC", [row["slchd_establishment_key"]]))""")

md("""### Q8. STELLA GRILL's inspection scores have fluctuated — should I be concerned?

Higher `inspection_score` = worse (more/severer violation points); see `semantic/ontology.json`'s `InspectionTrend` sign convention. A first-vs-last delta alone can hide a real mid-history spike, so this also pulls `inspection_type_id` (Routine=1, Followup=2, ...) to check whether any high score was caught and closed out by an immediate re-inspection, and compares against the countywide score distribution (Q11) so "high" has a reference point.""")
code("""stella = q("SELECT * FROM establishment_keys WHERE lower(name) LIKE '%stella grill%'")
display(stella)
if len(stella):
    key = stella.iloc[0]["slchd_establishment_key"]
    history = q("SELECT inspection_date, inspection_score, inspection_type_id FROM inspections WHERE slchd_establishment_key = ? ORDER BY inspection_date", [key])
    display(history)
    # Countywide reference queried fresh here (not reused from Q11) since Q11's cell
    # runs later in the notebook -- this cell can't depend on a variable that doesn't
    # exist yet at execution time.
    county_scores = q("SELECT inspection_score FROM inspections WHERE inspection_score IS NOT NULL")
    print("Stella Grill score stats:", history["inspection_score"].describe().to_dict())
    print("Countywide score stats (all inspections):", county_scores["inspection_score"].describe().to_dict())
    fig = px.line(history, x="inspection_date", y="inspection_score", markers=True, title="Stella Grill inspection score over time")
    fig.show()

    followups = history[history["inspection_type_id"] == 2]
    if len(followups):
        print(f"\\n{len(followups)} Followup inspection(s) found -- checking whether they immediately re-inspected a bad Routine score:")
        for _, f in followups.iterrows():
            prior = history[history["inspection_date"] < f["inspection_date"]]
            if len(prior):
                prior_row = prior.iloc[-1]
                gap_days = (f["inspection_date"] - prior_row["inspection_date"]).days
                print(f"  {prior_row['inspection_date']} (score {prior_row['inspection_score']}, "
                      f"type {prior_row['inspection_type_id']}) -> {gap_days} day(s) later -> "
                      f"{f['inspection_date']} Followup (score {f['inspection_score']})")

    score_delta = history["inspection_score"].iloc[-1] - history["inspection_score"].iloc[0]
    print(f"\\nscore_delta (last - first) = {score_delta}")
    if len(history) < 2:
        trend = "insufficient_data"
    elif score_delta < -9:
        trend = "improving"
    elif score_delta > 1:
        trend = "worsening"
    else:
        trend = "stable"
    print("InspectionTrend classification (per semantic/ontology.json):", trend)

    county_mean = county_scores["inspection_score"].mean()
    n_above_mean = int((history["inspection_score"] > county_mean).sum())
    worst = history.loc[history["inspection_score"].idxmax()]
    print(
        f"\\nCaveat: the delta-only classification is this project's canonical rule, but it's "
        f"an incomplete answer to 'should I be concerned' on its own -- it says nothing about "
        f"the {worst['inspection_date']} inspection scoring {worst['inspection_score']} "
        f"(Stella's max, vs. a countywide mean of {county_mean:.1f}), or that "
        f"{n_above_mean} of Stella's {len(history)} inspections on record scored above the "
        f"countywide mean. A well-supported answer should surface both: the single worst "
        f"inspection was caught and closed out fast (see the Followup check above), but "
        f"Stella's typical score has run persistently higher than average even after that "
        f"incident -- 'improving' by the raw delta, but not clearly 'safe now.'"
    )""")

md("""### Q9. What does the issue category "cold holding" mean?""")
code("""cold_holding_mapping = VIOLATION_MAP[VIOLATION_MAP["violation_phr"].str.contains("cold holding", case=False, na=False)]
display(cold_holding_mapping)
n_cited = q("SELECT COUNT(*) AS n FROM violations WHERE lower(violation_phr) LIKE '%cold holding%'").iloc[0]["n"]
print(f"Cited {n_cited} times in the violation history.")
print()
regulation_excerpt("cold holding temperature requirement")""")

md("### Q10. Geographic spread of restaurants with at least one critical violation, on a map")
code("""critical_establishments = q(\"\"\"
    SELECT DISTINCT e.name, e.address, ST_Y(e.geom) AS latitude, ST_X(e.geom) AS longitude
    FROM establishments e
    JOIN inspections i ON i.slchd_establishment_key = e.slchd_establishment_key
    JOIN violations v ON v.inspection_id = i.inspection_id
    JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
    WHERE vc.critical AND e.geom IS NOT NULL
\"\"\")
print(f"{len(critical_establishments)} establishments with >=1 critical violation and known coordinates")
fig = px.scatter_map(critical_establishments, lat="latitude", lon="longitude", hover_name="name", zoom=9, height=450,
                      title="Establishments with a critical violation on record")
fig.show()""")

md("### Q11. Detailed visual analytics and statistics of inspection scores across all establishments")
code("""all_scores = q("SELECT inspection_score FROM inspections WHERE inspection_score IS NOT NULL")
print(all_scores["inspection_score"].describe())
fig = px.histogram(all_scores, x="inspection_score", nbins=30, title="Inspection score distribution (all inspections)")
fig.show()""")

md("### Q12. Which restaurants' critical violations increased vs. decreased over the last 5 years")
code("""trend_data = q(\"\"\"
    SELECT ek.name, ek.slchd_establishment_key, i.inspection_date, i.inspection_id,
           COUNT(*) FILTER (WHERE vc.critical) AS critical_in_inspection
    FROM establishment_keys ek
    JOIN inspections i ON i.slchd_establishment_key = ek.slchd_establishment_key
    LEFT JOIN violations v ON v.inspection_id = i.inspection_id
    LEFT JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
    WHERE i.inspection_date >= (SELECT MAX(inspection_date) FROM inspections) - INTERVAL 5 YEAR
    GROUP BY ek.name, ek.slchd_establishment_key, i.inspection_date, i.inspection_id
\"\"\")

results = []
for key, g in trend_data.groupby("slchd_establishment_key"):
    g = g.sort_values("inspection_date")
    if len(g) < 2:
        continue
    delta = g["critical_in_inspection"].iloc[-1] - g["critical_in_inspection"].iloc[0]
    results.append({"name": g["name"].iloc[0], "n_inspections": len(g),
                     "first_critical": g["critical_in_inspection"].iloc[0],
                     "last_critical": g["critical_in_inspection"].iloc[-1], "delta": delta})
trend_df = pd.DataFrame(results)
print(f"{len(trend_df)} establishments with >=2 inspections in the last 5 years")
print("\\nIncreased (delta > 0):")
display(trend_df[trend_df["delta"] > 0].sort_values("delta", ascending=False))
print("\\nDecreased (delta < 0):")
display(trend_df[trend_df["delta"] < 0].sort_values("delta"))""")

md("""### Q13. Which street has the highest number of 3-star restaurants?

Two independent choices affect this answer, and got tangled together on the first
pass: (1) "3-star" literal (`avg_rating == 3.0`) vs. rounded-band (`[2.5, 3.5)`), and
(2) what counts as "the same street." `street_of()` (used above for Q1's addresses)
keeps the full segment including house number -- e.g. "10450 State St" and "500 State
St" count as different streets -- which is why the literal reading degenerates into a
78-way tie at 1 each: house numbers are almost never shared. `base_street()` strips
the leading house-number token (and any unit/suite suffix) and groups by
`(base_street, city)` -- keeping the city, since "State St" in Sandy and "State St" in
Murray are different physical streets that happen to share a name; collapsing across
cities (as a couple of the actual agent runs did) overcounts by conflating them. This
grouping is what actually answers the question meaningfully.""")
code("""three_star = q("SELECT name, address FROM establishments WHERE avg_rating = 3.0")
three_star["base_street"] = three_star.apply(lambda r: base_street(r["name"], r["address"]), axis=1)
three_star["city"] = three_star["address"].map(city_of)
three_star = three_star[three_star["base_street"] != ""]
print("Exact avg_rating == 3.0, grouped by (base_street, city):")
display(three_star.groupby(["base_street", "city"]).size().sort_values(ascending=False).head(10))

three_star_band = q("SELECT name, address FROM establishments WHERE avg_rating >= 2.5 AND avg_rating < 3.5")
three_star_band["base_street"] = three_star_band.apply(lambda r: base_street(r["name"], r["address"]), axis=1)
three_star_band["city"] = three_star_band["address"].map(city_of)
three_star_band = three_star_band[three_star_band["base_street"] != ""]
print("\\nRounded band [2.5, 3.5), grouped by (base_street, city):")
display(three_star_band.groupby(["base_street", "city"]).size().sort_values(ascending=False).head(10))""")

md("### Q14. Thai vs. Korean: which has the higher average rating? Which has more violations?")
code("""def cuisine_summary(keyword: str) -> pd.Series:
    df = q(\"\"\"
        SELECT DISTINCT e.gmap_id, e.name, e.avg_rating, e.slchd_establishment_key
        FROM establishments e
        JOIN establishment_categories ec ON ec.gmap_id = e.gmap_id
        JOIN category c ON c.category_id = ec.category_id
        WHERE lower(c.category) LIKE ?
    \"\"\", [f"%{keyword}%"])
    violation_count = q(\"\"\"
        SELECT COUNT(*) AS n FROM establishments e
        JOIN establishment_categories ec ON ec.gmap_id = e.gmap_id
        JOIN category c ON c.category_id = ec.category_id
        JOIN inspections i ON i.slchd_establishment_key = e.slchd_establishment_key
        JOIN violations v ON v.inspection_id = i.inspection_id
        WHERE lower(c.category) LIKE ?
    \"\"\", [f"%{keyword}%"]).iloc[0]["n"]
    return pd.Series({"n_establishments": len(df), "avg_rating": df["avg_rating"].mean(),
                       "n_matched_to_inspection": df["slchd_establishment_key"].notna().sum(),
                       "total_violations": violation_count})

comparison = pd.DataFrame({"Thai": cuisine_summary("thai"), "Korean": cuisine_summary("korean")})
display(comparison)""")

# ============================================================ Section 2
md("""## No-checkpoint / no-memory questions — Qualitative

**No single correct answer** — these are subjective recommendation questions. What follows is the grounding candidate data a well-supported answer should be consistent with.""")

md("""### Q15. Breakfast recommendation near Rose Park, not sweet

"Rose Park" is approximated by ZIP 84116 (address string match) — there's no neighborhood-boundary field in this dataset, so this is the closest defensible proxy. "Not sweet" isn't something the data can filter on (no menu-item-level data) — flagging that honestly rather than faking a filter.""")
code("""breakfast_near_rose_park = q(\"\"\"
    SELECT DISTINCT e.name, e.address, e.avg_rating, e.num_of_reviews, e.price
    FROM establishments e
    JOIN establishment_categories ec ON ec.gmap_id = e.gmap_id
    JOIN category c ON c.category_id = ec.category_id
    WHERE lower(c.category) LIKE '%breakfast%' AND e.address LIKE '%84116%'
    ORDER BY e.avg_rating DESC NULLS LAST
\"\"\")
print(f"{len(breakfast_near_rose_park)} breakfast-tagged establishments in ZIP 84116 (Rose Park)")
display(breakfast_near_rose_park)
print("A well-grounded agent answer should draw from this list (or explicitly broaden beyond it and say so) — not invent a restaurant not in this set.")""")

# ============================================================ Section 3
md("## Memory-condition questions — Quantitative")

md("### Thread A, turn 1. How many establishments have a Salt Lake County health inspection on record?")
code("""n_matched = q("SELECT COUNT(*) AS n FROM establishments WHERE slchd_establishment_key IS NOT NULL").iloc[0]["n"]
n_total = q("SELECT COUNT(*) AS n FROM establishments").iloc[0]["n"]
print(f"{n_matched} of {n_total} establishments ({n_matched/n_total:.1%}) have a matched SLCHD inspection record.")""")

md("### Thread A, turn 2. Among them, the distribution and timeline of health inspections")
code("""matched_scores = q(\"\"\"
    SELECT i.inspection_score, i.inspection_date
    FROM inspections i
    WHERE i.slchd_establishment_key IN (SELECT slchd_establishment_key FROM establishments WHERE slchd_establishment_key IS NOT NULL)
\"\"\")
print(matched_scores["inspection_score"].describe())
fig1 = px.histogram(matched_scores, x="inspection_score", nbins=30, title="Inspection score distribution (matched establishments)")
fig1.show()

timeline = matched_scores.copy()
timeline["year"] = pd.to_datetime(timeline["inspection_date"]).dt.year
fig2 = px.histogram(timeline, x="year", title="Inspections per year (matched establishments)")
fig2.show()""")

md("### Thread B, turn 1. Highest-rated Chinese restaurant vs. most-reviewed Chinese restaurant")
code("""chinese = q(\"\"\"
    SELECT DISTINCT e.gmap_id, e.name, e.address, e.avg_rating, e.num_of_reviews, e.price, e.slchd_establishment_key
    FROM establishments e
    JOIN establishment_categories ec ON ec.gmap_id = e.gmap_id
    JOIN category c ON c.category_id = ec.category_id
    WHERE lower(c.category) LIKE '%chinese%'
\"\"\")
highest_rated = chinese.sort_values(["avg_rating", "num_of_reviews"], ascending=False).iloc[0]
most_reviewed = chinese.sort_values("num_of_reviews", ascending=False).iloc[0]
print("Highest rated Chinese restaurant:")
display(highest_rated)
print("\\nMost reviewed Chinese restaurant:")
display(most_reviewed)""")

md("""### Thread B, turn 2. Which do you recommend I try?

No single correct answer — a reasonable response should weigh the two candidates above (rating vs. review-count-as-social-proof) rather than pick one without justification.""")

md("## Memory-condition questions — Qualitative")

md("""### Thread C, turn 1. How hard is it to find halal food options in Salt Lake County?

Note: the `establishment_attributes` table is Google's crowdsourced attribute data, not a certification registry — it includes a "Halal food" tag on several McDonald's/Sonic Drive-In locations, which likely reflects an individual franchise's menu offering rather than whole-chain certification. Flagging this so it doesn't read as a query bug; it's a real (if questionable) property of the source data.""")
code("""halal = q(\"\"\"
    SELECT DISTINCT e.name, e.address, e.avg_rating, e.num_of_reviews
    FROM establishments e
    LEFT JOIN establishment_categories ec ON ec.gmap_id = e.gmap_id
    LEFT JOIN category c ON c.category_id = ec.category_id
    LEFT JOIN establishment_attributes ea ON ea.gmap_id = e.gmap_id
    WHERE lower(c.category) LIKE '%halal%' OR lower(ea.attribute) LIKE '%halal%'
    ORDER BY e.avg_rating DESC NULLS LAST
\"\"\")
print(f"{len(halal)} establishments tagged halal (by category or attribute) out of {n_total} total ({len(halal)/n_total:.2%}).")
display(halal)""")

md("""### Thread C, turn 2. If I like vegetables, which do you recommend I try?

No single correct answer. Cross-referencing the halal set above against vegetarian-friendly signals, for whichever candidates a grounded answer could point to.""")
code("""halal_gmap_ids = q(\"\"\"
    SELECT DISTINCT e.gmap_id
    FROM establishments e
    LEFT JOIN establishment_categories ec ON ec.gmap_id = e.gmap_id
    LEFT JOIN category c ON c.category_id = ec.category_id
    LEFT JOIN establishment_attributes ea ON ea.gmap_id = e.gmap_id
    WHERE lower(c.category) LIKE '%halal%' OR lower(ea.attribute) LIKE '%halal%'
\"\"\")["gmap_id"].tolist()

placeholders = ",".join(["?"] * len(halal_gmap_ids)) if halal_gmap_ids else "NULL"
halal_and_veg = q(f\"\"\"
    SELECT DISTINCT e.name, e.address, e.avg_rating
    FROM establishments e
    LEFT JOIN establishment_attributes ea ON ea.gmap_id = e.gmap_id
    WHERE e.gmap_id IN ({placeholders}) AND lower(ea.attribute) LIKE '%vegetarian%'
\"\"\", halal_gmap_ids)
print(f"{len(halal_and_veg)} of the halal-tagged establishments also have a 'Vegetarian options' attribute:")
display(halal_and_veg)
print("If this set is empty, a grounded answer should say the data doesn't support a halal+vegetarian-specific pick, rather than inventing one.")""")

nb["cells"] = cells
nbf.write(nb, ROOT / "ground_truth_answers.ipynb")
print(f"wrote {len(cells)} cells")
