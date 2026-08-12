"""Shared helper for all three dashboards: runs a create_agent()-built
agent and turns its message-list result into the final answer text plus
(a) a human-readable Action/Observation trace for the reasoning-trace
expander, and (b) for Variant 3, a structured `timeline` of
ReasoningSteps for the map/evidence reasoning view.

The timeline is built entirely from the actual tool-call trace — never
from LLM narration — so it can't show a step the agent didn't really
take. Step captions are generated from the tool name + args, not asked
of the model.
"""
import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
import plotly.express as px
from langchain_core.messages import AIMessage, ToolMessage

# Tool calls that manipulate/filter the candidate pool and are worth a
# timeline step. get_schema/get_column_glossary are excluded — they're
# metadata lookups, not reasoning about restaurants.
_TIMELINE_KIND: dict[str, str] = {
    "search_establishments": "map",
    "run_sql": "sql",
    "retrieve_regulation": "citation",
    "classify_violation": "classification",
    "get_inspection_history": "inspection_history",
    "plot_chart": "chart",
}

StepKind = Literal["map", "sql", "citation", "classification", "inspection_history", "chart"]


@dataclass
class ReasoningStep:
    index: int
    kind: StepKind
    tool_name: str
    tool_args: dict[str, Any]
    caption: str
    rows: list[dict] = field(default_factory=list)


def _as_text(content) -> str:
    """Normalize a message's `.content` to plain text.

    Most providers (Groq, Ollama) return a plain string. Some (Gemini)
    return a list of content blocks (`{"type": "text", "text": ...}`,
    plus non-text blocks like thought signatures) — pull just the text
    parts out of those.
    """
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "".join(parts)
    return str(content)


def _build_trace(messages) -> str:
    trace_lines = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for call in msg.tool_calls:
                trace_lines.append(f"Action: {call['name']}({call['args']})")
        elif isinstance(msg, ToolMessage):
            trace_lines.append(f"Observation: {_as_text(msg.content)}")
    return "\n\n".join(trace_lines)


def _caption_for_call(name: str, args: dict) -> str:
    """Plain-language caption generated from the tool name + args — not
    written by the LLM, so it can't describe something that didn't
    actually happen."""
    if name == "search_establishments":
        parts = []
        if args.get("name_contains"):
            parts.append(f"name contains '{args['name_contains']}'")
        if args.get("near_lat") is not None and args.get("near_lon") is not None:
            radius = args.get("radius_mi")
            parts.append(f"within {radius} mi" if radius else "near a location")
        if args.get("min_rating") is not None:
            parts.append(f"rating ≥ {args['min_rating']}")
        if args.get("max_price_level") is not None:
            parts.append(f"price ≤ {'$' * int(args['max_price_level'])}")
        if args.get("category_contains"):
            parts.append(f"category contains '{args['category_contains']}'")
        if args.get("require_inspection_data"):
            parts.append("has SLCHD inspection history")
        if args.get("min_inspection_score") is not None:
            parts.append(f"inspection score ≥ {args['min_inspection_score']}")
        if args.get("max_inspection_score") is not None:
            parts.append(f"inspection score ≤ {args['max_inspection_score']}")
        return "Searching establishments: " + (", ".join(parts) if parts else "no filters")
    if name == "run_sql":
        return "Running a SQL query"
    if name == "retrieve_regulation":
        return f"Looking up regulation text for '{args.get('query', '')}'"
    if name == "classify_violation":
        return f"Classifying violation type for '{args.get('violation_phr', '')}'"
    if name == "get_inspection_history":
        return f"Pulling inspection history for {args.get('slchd_establishment_key', '')}"
    if name == "plot_chart":
        return f"Charting: {args.get('title') or args.get('chart_type', '')}"
    return f"{name}({args})"


def _recover_narrative(raw_text: str) -> str:
    """When structured-output coercion fails, the model's raw final message
    is often still its JSON attempt at HypothesisResponse — just not one
    that fully validated (or it's wrapped in prose/```json fences). Rather
    than showing that JSON blob to the user as if it were the answer, pull
    narrative_answer back out of it when possible. Falls back to the raw
    text unchanged if it isn't JSON-shaped at all."""
    text = raw_text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return raw_text
    try:
        parsed = json.loads(match.group(0))
    except (json.JSONDecodeError, TypeError):
        return raw_text
    if isinstance(parsed, dict) and isinstance(parsed.get("narrative_answer"), str):
        return parsed["narrative_answer"]
    return raw_text


def _parse_tool_result(content) -> tuple[list[dict], Any]:
    """ToolMessage content is a JSON string for our data tools. Returns
    (rows, raw_parsed) — rows is [] if the content isn't the
    {"rows": [...]} shape (e.g. retrieve_regulation's plain text)."""
    text = _as_text(content)
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return [], text
    if isinstance(parsed, dict) and isinstance(parsed.get("rows"), list):
        return parsed["rows"], parsed
    return [], parsed


def _build_timeline(messages) -> list[ReasoningStep]:
    # Tool calls and their results arrive as separate messages; pair them
    # by tool_call_id (ToolMessage carries the id of the call it answers).
    results_by_id: dict[str, ToolMessage] = {
        msg.tool_call_id: msg for msg in messages if isinstance(msg, ToolMessage)
    }

    steps: list[ReasoningStep] = []
    for msg in messages:
        if not (isinstance(msg, AIMessage) and msg.tool_calls):
            continue
        for call in msg.tool_calls:
            kind = _TIMELINE_KIND.get(call["name"])
            if kind is None:
                continue  # get_schema / get_column_glossary — not a reasoning step
            result_msg = results_by_id.get(call["id"])
            rows, _ = _parse_tool_result(result_msg.content) if result_msg else ([], None)
            steps.append(
                ReasoningStep(
                    index=len(steps),
                    kind=kind,
                    tool_name=call["name"],
                    tool_args=call["args"],
                    caption=_caption_for_call(call["name"], call["args"]),
                    rows=rows,
                )
            )
    return steps


def _auto_map_figure(rows: list[dict]):
    """A plain establishment map built straight from data — no agent
    involvement, so it can't be skipped by a model that forgot to chart."""
    df = pd.DataFrame(rows).dropna(subset=["latitude", "longitude"])
    if df.empty:
        return None
    fig = px.scatter_map(
        df, lat="latitude", lon="longitude", hover_name="name",
        hover_data={"avg_rating": ":.1f", "latitude": False, "longitude": False},
        zoom=9, height=420,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
    return fig


def _auto_bar_figure(rows: list[dict]):
    """Best-effort bar chart from an arbitrary tabular tool result: first
    text-like column as labels, first non-id numeric column as values.
    Used only as a last-resort fallback (run_sql results, which have no
    fixed shape) — search_establishments' results go through
    _auto_map_figure instead, which is always the better fit."""
    if not rows:
        return None
    df = pd.DataFrame(rows)
    skip_ids = {"gmap_id", "slchd_establishment_key"}
    # Pandas versions differ on whether a string column reports dtype
    # object or a dedicated string dtype (observed both) — select on "not
    # numeric" rather than a specific dtype value, which is stable either way.
    label_col = next(
        (c for c in df.columns if not pd.api.types.is_numeric_dtype(df[c]) and c not in skip_ids), None
    )
    skip_numeric = {"latitude", "longitude"}
    numeric_col = next(
        (c for c in df.columns if pd.api.types.is_numeric_dtype(df[c]) and c not in skip_numeric), None
    )
    if label_col is None or numeric_col is None:
        return None
    plot_df = df.head(20)
    fig = px.bar(plot_df, x=numeric_col, y=label_col, orientation="h")
    fig.update_layout(yaxis=dict(autorange="reversed"), height=400, margin=dict(l=10, r=10, t=30, b=10))
    return fig


def _ensure_visualization(chart_sink: list, candidate_sink: list, messages) -> None:
    """Guarantee at least one chart lands in chart_sink, without relying on
    the model to remember plot_chart. Prefers a map of whatever
    search_establishments returned (it's establishment data, a map is
    almost always the right form); falls back to an auto-built bar chart
    from the last tabular run_sql result if the answer never called
    search_establishments."""
    if chart_sink:
        return
    if candidate_sink:
        fig = _auto_map_figure(candidate_sink)
        if fig is not None:
            chart_sink.append(fig)
            return
    for msg in reversed(messages):
        if isinstance(msg, ToolMessage):
            rows, _ = _parse_tool_result(msg.content)
            if rows:
                fig = _auto_bar_figure(rows)
                if fig is not None:
                    chart_sink.append(fig)
                return


def run_agent(agent, prompt: str, chart_sink: list, candidate_sink: list) -> tuple[str, str]:
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    messages = result["messages"]
    output = _as_text(messages[-1].content)
    _ensure_visualization(chart_sink, candidate_sink, messages)
    return output, _build_trace(messages)


def run_structured_agent(agent, prompt: str, chart_sink: list, candidate_sink: list):
    """For agents built with response_format= (Variant 3). Returns
    (structured_response, trace_text, timeline) — structured_response is
    always a HypothesisResponse, never raw text.

    LangChain's structured-output coercion can fail to validate for a
    weaker/local model (documented in app/README's known limitations) even
    though the tool calls it made along the way succeeded fine — the
    candidate_pool built from candidate_sink doesn't depend on that final
    coercion step, so on failure we synthesize a minimal HypothesisResponse
    (hypothesis='none', low confidence, plain-text answer) around the same
    real tool-call data rather than losing it. This is what makes the
    Reasoning tab reliable regardless of whether the model's final
    formatting step happened to validate.

    candidate_sink is the same list passed into tools.make_tools() for
    this request — every search_establishments result landed there during
    the run, in call order. It overwrites/fills candidate_pool here rather
    than trusting the model to reproduce it, per the same no-LLM-narration
    rule the timeline follows.
    """
    from schemas import CandidatePoolItem, HypothesisResponse

    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    messages = result["messages"]
    structured = result.get("structured_response")

    # search_establishments' row shape (tools.py) uses
    # most_recent_inspection_score for clarity to the LLM;
    # CandidatePoolItem's field is inspection_score — map explicitly rather
    # than **row, since Pydantic silently drops/defaults mismatched keys
    # instead of erroring.
    pool = [
        CandidatePoolItem(
            gmap_id=row["gmap_id"],
            name=row.get("name"),
            address=row.get("address"),
            latitude=row.get("latitude"),
            longitude=row.get("longitude"),
            avg_rating=row.get("avg_rating"),
            num_of_reviews=row.get("num_of_reviews"),
            price=row.get("price"),
            distance_mi=row.get("distance_mi"),
            slchd_establishment_key=row.get("slchd_establishment_key"),
            inspection_score=row.get("most_recent_inspection_score"),
            critical_violation_count=row.get("critical_violation_count"),
            total_violation_count=row.get("total_violation_count"),
        )
        for row in candidate_sink
        if row.get("gmap_id")
    ]

    if structured is None:
        structured = HypothesisResponse(
            narrative_answer=_recover_narrative(_as_text(messages[-1].content)),
            hypothesis="none",
            confidence="low",
            candidate_pool=pool,
        )
    else:
        structured.candidate_pool = pool

    _ensure_visualization(chart_sink, candidate_sink, messages)
    return structured, _build_trace(messages), _build_timeline(messages)
