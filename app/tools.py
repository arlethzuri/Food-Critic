"""Tools for the ReAct agent against db/food_health.duckdb (the normalized
schema: establishments, establishment_keys, inspections, violations,
violation_codes, review, category, ...).

get_schema / get_column_glossary mirror db/schema.dbml and
semantic/data_dictionary.json — keep those in sync if the schema changes,
not this file's docstrings.
"""
import json
import math
from pathlib import Path

import plotly.express as px
from langchain_core.tools import tool

from data_layer import SafeConnection

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DBML = (ROOT / "db" / "schema.dbml").read_text(encoding="utf-8")
DATA_DICTIONARY = json.loads((ROOT / "semantic" / "data_dictionary.json").read_text(encoding="utf-8"))

METERS_PER_MILE = 1609.344


def _run_select(con: SafeConnection, query: str):
    q = query.strip().rstrip(";")
    if not q.lower().startswith(("select", "with")):
        raise ValueError("Only SELECT/WITH queries are allowed.")
    return con.execute(q).fetchdf()


def _records(df) -> list[dict]:
    """df.to_dict(orient='records'), with float NaN normalized to None.

    A column that's SQL NULL for some rows and a real string for others
    can come back from fetchdf() as an object column where the nulls are
    float('nan') rather than None (observed on slchd_establishment_key) —
    NaN isn't valid JSON (json.dumps emits the non-standard `NaN` token)
    and fails Pydantic's `str | None` validation outright. Normalize once
    here rather than at every call site.
    """
    rows = df.to_dict(orient="records")
    for row in rows:
        for k, v in row.items():
            if isinstance(v, float) and math.isnan(v):
                row[k] = None
    return rows


def make_tools(con: SafeConnection, chart_sink: list, candidate_sink: list):
    """Build tool instances bound to this DuckDB connection and this
    request's chart_sink/candidate_sink (plain lists the caller reads
    after the agent run — kept per-request rather than global so
    concurrent Streamlit sessions don't leak into each other).

    candidate_sink collects every establishment search_establishments
    returns, in call order — this is the source for HypothesisResponse's
    candidate_pool (map + Strictness slider in the UI)."""

    @tool
    def get_schema() -> str:
        """Return the full table/column/type/foreign-key schema (db/schema.dbml). Call this first if you're unsure what's queryable. For a specific column's meaning or enum values beyond its type, call get_column_glossary."""
        return SCHEMA_DBML

    @tool
    def get_column_glossary(table_dot_column: str) -> str:
        """Look up one column's meaning/enum values/unit from the data dictionary, e.g. 'establishments.price' or 'violation_codes.asterisk_count'. Only covers columns with non-obvious semantics — most columns are self-explanatory from get_schema's types alone."""
        entry = DATA_DICTIONARY["columns"].get(table_dot_column)
        if entry is None:
            return f"No glossary entry for '{table_dot_column}' — it's probably self-explanatory from get_schema."
        return json.dumps(entry, default=str)

    @tool
    def run_sql(query: str) -> str:
        """Run a read-only DuckDB SQL SELECT/WITH query against any table in the schema (see get_schema). Returns up to 50 rows as JSON. Use this for any count, ranking, filter, or aggregate you need before answering or before calling plot_chart — never state a number you haven't gotten from this tool."""
        try:
            df = _run_select(con, query)
        except Exception as e:
            return f"SQL error: {e}"
        truncated = len(df) > 50
        payload = {
            "row_count": len(df),
            "truncated": truncated,
            "rows": _records(df.head(50)),
        }
        return json.dumps(payload, default=str)

    SORT_COLUMNS = {
        "avg_rating": "e.avg_rating",
        "num_of_reviews": "e.num_of_reviews",
        "distance_mi": "distance_mi",
        "inspection_score": "most_recent_inspection_score",
        "critical_violation_count": "critical_violation_count",
        "total_violation_count": "total_violation_count",
    }

    @tool
    def search_establishments(
        name_contains: str = "",
        near_lat: float | None = None,
        near_lon: float | None = None,
        radius_mi: float | None = None,
        min_rating: float | None = None,
        max_price_level: int | None = None,
        category_contains: str = "",
        require_inspection_data: bool = False,
        min_inspection_score: float | None = None,
        max_inspection_score: float | None = None,
        min_critical_violations: int | None = None,
        sort_by: str = "avg_rating",
        sort_desc: bool = True,
        limit: int = 50,
    ) -> str:
        """Search establishments with structured filters — the preferred way to find candidate restaurants (over hand-writing SQL against `establishments`/`violations`), because every result it returns becomes part of the map/evidence view shown to the user. Use this even for a single named establishment (name_contains), and for ANY ranking question ("top N by X") via sort_by — never hand-write that ranking in run_sql, or it won't appear on the map/evidence view.

        name_contains: case-insensitive substring match against establishments.name — use this to look up one specific restaurant by name.
        near_lat/near_lon/radius_mi: geographic filter, radius in miles.
        min_rating: minimum avg_rating (1-5).
        max_price_level: 1=$, 2=$$, 3=$$$, 4=$$$$ — filters to price levels at or below this.
        category_contains: case-insensitive substring match against category.category (e.g. 'pizza', 'chinese') — NOT for restaurant names, use name_contains for that.
        require_inspection_data: only return establishments with a matched SLCHD inspection history (slchd_establishment_key set). Most establishments (98.4%) have none — set this only when the question specifically needs inspection/violation evidence.
        min_inspection_score/max_inspection_score: filter by most recent inspection_score (0=clean, higher=worse). Only meaningful combined with require_inspection_data.
        min_critical_violations: only return establishments with at least this many critical violations across their whole inspection history (use this for "restaurants with critical violations" style questions).
        sort_by: one of avg_rating (default), num_of_reviews, distance_mi (requires near_lat/near_lon), inspection_score, critical_violation_count, total_violation_count. Use critical_violation_count/total_violation_count for "most/worst violations" ranking questions.
        sort_desc: True (default) for highest-first — e.g. "top 10 by critical violations" is sort_by='critical_violation_count', sort_desc=True, limit=10. Set False for lowest/cleanest-first.
        limit: max rows to return (default 50).

        Returns up to `limit` establishments as JSON, each with gmap_id, name, address, latitude, longitude, avg_rating, num_of_reviews, price, distance_mi (if near_lat/near_lon given), slchd_establishment_key, most_recent_inspection_score (if matched), critical_violation_count, and total_violation_count."""
        # Named ($param) bindings — safe regardless of which optional filters
        # end up in the query, unlike positional (?) params where every
        # fragment has to independently track its position in the final SQL.
        where = []
        params: dict = {"limit": limit}

        if name_contains:
            where.append("lower(e.name) LIKE '%' || lower($name_contains) || '%'")
            params["name_contains"] = name_contains
        if min_rating is not None:
            where.append("e.avg_rating >= $min_rating")
            params["min_rating"] = min_rating
        if max_price_level is not None:
            where.append("e.price IS NOT NULL AND length(e.price) <= $max_price_level")
            params["max_price_level"] = max_price_level
        if require_inspection_data:
            where.append("e.slchd_establishment_key IS NOT NULL")
        if category_contains:
            where.append(
                "e.gmap_id IN ("
                "SELECT ec.gmap_id FROM establishment_categories ec "
                "JOIN category c ON c.category_id = ec.category_id "
                "WHERE lower(c.category) LIKE '%' || lower($category_contains) || '%')"
            )
            params["category_contains"] = category_contains

        dist_select = "NULL AS distance_mi"
        if near_lat is not None and near_lon is not None:
            params["near_lon"] = near_lon
            params["near_lat"] = near_lat
            dist_select = (
                f"ST_Distance_Sphere(e.geom, ST_Point($near_lon, $near_lat)) / {METERS_PER_MILE} AS distance_mi"
            )
            if radius_mi is not None:
                where.append(
                    f"ST_Distance_Sphere(e.geom, ST_Point($near_lon, $near_lat)) / {METERS_PER_MILE} <= $radius_mi"
                )
                params["radius_mi"] = radius_mi

        # Always join the most-recent-inspection score and violation counts
        # (cheap, and useful on the map/evidence view regardless of whether
        # the agent filtered/sorted on them) — only the WHERE/ORDER BY
        # clauses are conditional on the agent's actual arguments.
        score_join = """
        LEFT JOIN (
            SELECT slchd_establishment_key, inspection_score,
                   row_number() OVER (
                       PARTITION BY slchd_establishment_key ORDER BY inspection_date DESC
                   ) AS rn
            FROM inspections
        ) i ON i.slchd_establishment_key = e.slchd_establishment_key AND i.rn = 1
        """
        score_select = "i.inspection_score AS most_recent_inspection_score"
        if min_inspection_score is not None:
            where.append("i.inspection_score >= $min_inspection_score")
            params["min_inspection_score"] = min_inspection_score
        if max_inspection_score is not None:
            where.append("i.inspection_score <= $max_inspection_score")
            params["max_inspection_score"] = max_inspection_score

        violation_join = """
        LEFT JOIN (
            SELECT i2.slchd_establishment_key,
                   count(*) FILTER (WHERE vc2.critical) AS critical_violation_count,
                   count(*) AS total_violation_count
            FROM inspections i2
            JOIN violations v2 ON v2.inspection_id = i2.inspection_id
            JOIN violation_codes vc2 ON vc2.violation_code_id = v2.violation_code_id
            GROUP BY i2.slchd_establishment_key
        ) vcount ON vcount.slchd_establishment_key = e.slchd_establishment_key
        """
        violation_select = (
            "COALESCE(vcount.critical_violation_count, 0) AS critical_violation_count, "
            "COALESCE(vcount.total_violation_count, 0) AS total_violation_count"
        )
        if min_critical_violations is not None:
            where.append("COALESCE(vcount.critical_violation_count, 0) >= $min_critical_violations")
            params["min_critical_violations"] = min_critical_violations

        where_sql = f"WHERE {' AND '.join(where)}" if where else ""
        sort_col = SORT_COLUMNS.get(sort_by, "e.avg_rating")
        sort_dir = "DESC" if sort_desc else "ASC"

        query = f"""
            SELECT
                e.gmap_id, e.name, e.address, ST_Y(e.geom) AS latitude, ST_X(e.geom) AS longitude,
                e.avg_rating, e.num_of_reviews, e.price, e.slchd_establishment_key,
                {dist_select}, {score_select}, {violation_select}
            FROM establishments e
            {score_join}
            {violation_join}
            {where_sql}
            ORDER BY {sort_col} {sort_dir} NULLS LAST
            LIMIT $limit
        """
        try:
            df = con.execute(query, params).fetchdf()
        except Exception as e:
            return f"SQL error: {e}"

        rows = _records(df)
        candidate_sink.extend(rows)
        return json.dumps({"row_count": len(rows), "rows": rows}, default=str)

    @tool
    def get_inspection_history(slchd_establishment_key: str) -> str:
        """Return every inspection + its cited violations for one SLCHD listing, most recent first. Use this to build evidence for a hypothesis once search_establishments has identified a matched candidate (slchd_establishment_key is set)."""
        query = """
            SELECT i.inspection_id, i.inspection_date, it.description AS inspection_type,
                   i.inspection_score, vc.code_text, vc.asterisk_count, vc.critical,
                   v.violation_description, v.violation_occurrences, v.violation_cos, v.violation_phr
            FROM inspections i
            LEFT JOIN inspection_types it ON it.inspection_type_id = i.inspection_type_id
            LEFT JOIN violations v ON v.inspection_id = i.inspection_id
            LEFT JOIN violation_codes vc ON vc.violation_code_id = v.violation_code_id
            WHERE i.slchd_establishment_key = ?
            ORDER BY i.inspection_date DESC
        """
        try:
            df = con.execute(query, [slchd_establishment_key]).fetchdf()
        except Exception as e:
            return f"SQL error: {e}"
        if df.empty:
            return f"No inspection history found for slchd_establishment_key={slchd_establishment_key!r}."
        return json.dumps({"row_count": len(df), "rows": _records(df)}, default=str)

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

    return [
        get_schema,
        get_column_glossary,
        run_sql,
        search_establishments,
        get_inspection_history,
        plot_chart,
    ]
