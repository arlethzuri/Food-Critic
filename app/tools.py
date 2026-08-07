"""Tools for the Variant 1 ReAct agent: raw SQL access to the merged CSV
(via DuckDB) plus a charting tool that renders results into the dashboard.
No RAG, no ontology, no reviews — every answer must be grounded in a SQL
result against `inspections`.

Column meanings mirror data/README.md; keep the two in sync if the merged
schema changes.
"""
import json

import plotly.express as px
from langchain_core.tools import tool

from data_layer import SafeConnection

SCHEMA_HELP = """\
Table: inspections — one row per violation. Establishment and inspection \
fields (name, address, score, violation counts, ...) repeat on every \
violation row belonging to that inspection; an inspection with no \
violations still has exactly one row with empty violation_* fields.

Columns (all read as VARCHAR — cast before doing math):
  establishment_name            text
  establishment_type            text, e.g. 'Restaurants: plated', 'Mobiles: Food Carts'
  address                       text, street address
  city_state_zip                text, e.g. 'SANDY, UT 84070'
  contact_info                  text, phone (format varies by source)
  rank                          text, site's own rank/score field, often empty
  inspection_date               text, 'M/D/YYYY' — use strptime(inspection_date, '%m/%d/%Y') for dates
  inspection_type               text, e.g. '01 - Routine', '02 - Followup'
  inspection_score              text, numeric, may be ''
  count_critical_violations     text, numeric, may be ''
  count_noncritical_violations  text, numeric, may be ''
  violation_code                text, '' if this inspection had no violations
  violation_description         text, free-text description
  violation_critical             text, 'True'/'False'/''
  violation_occurrences         text, numeric, may be ''
  violation_cos                 text, 'True'/'False' — corrected on site
  violation_phr                 text, public-health-risk category / rule reference
  source                        text, 'friend_slc' or 'own_scrape'
  scraped_at                    text, ISO timestamp, may be ''

Gotchas:
  - Numeric-looking columns are VARCHAR. Filter empties before casting, e.g.:
    WHERE inspection_score != '' ... CAST(inspection_score AS DOUBLE)
  - A restaurant chain/location is identified by (establishment_name, address)
    together — names alone can repeat across different locations.
  - 'own_scrape' rows never have violation_code/violation_description filled in
    (that source only captured inspection-history summaries, not per-violation
    detail) — don't treat their absence as "no violations occurred".
"""


def _run_select(con: SafeConnection, query: str):
    q = query.strip().rstrip(";")
    if not q.lower().startswith(("select", "with")):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    return con.execute(q).fetchdf()


def make_tools(con: SafeConnection, chart_sink: list):
    """Build tool instances bound to this DuckDB connection and this
    request's chart_sink (a plain list the caller reads after the agent
    run — kept per-request rather than global so concurrent Streamlit
    sessions don't leak charts into each other)."""

    @tool
    def get_schema() -> str:
        """Return the inspections table's columns, meanings, and gotchas (empty-string numerics, date format, chain-location keys). Call this first if you're unsure what's queryable."""
        return SCHEMA_HELP

    @tool
    def run_sql(query: str) -> str:
        """Run a read-only DuckDB SQL SELECT/WITH query against the `inspections` table. Returns up to 50 rows as JSON. Use this for any count, ranking, filter, or aggregate you need before answering or before calling plot_chart — never state a number you haven't gotten from this tool."""
        try:
            df = _run_select(con, query)
        except Exception as e:
            return f"SQL error: {e}"
        truncated = len(df) > 50
        payload = {
            "row_count": len(df),
            "truncated": truncated,
            "rows": df.head(50).to_dict(orient="records"),
        }
        return json.dumps(payload, default=str)

    @tool
    def plot_chart(query: str, chart_type: str, x: str, y: str = "", color: str = "", title: str = "") -> str:
        """Run a DuckDB SQL query and render the result as a chart shown to the user. chart_type: one of bar, line, scatter, pie, histogram. x/y/color must be column names present in the query's SELECT output. Use this whenever the user's question calls for a visual rather than just a number."""
        try:
            df = _run_select(con, query)
        except Exception as e:
            return f"SQL error: {e}"
        if df.empty:
            return "Query returned no rows, nothing to plot."

        kind = chart_type.strip().lower()
        try:
            if kind == "bar":
                fig = px.bar(df, x=x, y=y or None, color=color or None, title=title or None)
            elif kind == "line":
                fig = px.line(df, x=x, y=y or None, color=color or None, title=title or None)
            elif kind == "scatter":
                fig = px.scatter(df, x=x, y=y or None, color=color or None, title=title or None)
            elif kind == "pie":
                fig = px.pie(df, names=x, values=y or None, title=title or None)
            elif kind == "histogram":
                fig = px.histogram(df, x=x, color=color or None, title=title or None)
            else:
                return f"Unknown chart_type '{chart_type}'. Use one of: bar, line, scatter, pie, histogram."
        except Exception as e:
            return f"Chart error: {e}"

        chart_sink.append(fig)
        return f"Chart created: '{title or kind}' ({kind}, {len(df)} rows). It will be shown to the user below your answer."

    return [get_schema, run_sql, plot_chart]
