"""Shared helper for all three dashboards: runs a create_agent()-built
agent and turns its message-list result into the final answer text plus
(a) a human-readable Action/Observation trace for the reasoning-trace
expander, and (b) for Variant 3, a structured `timeline` of
ReasoningSteps for the map/evidence reasoning view.

The timeline is built entirely from the actual tool-call trace — never
from LLM narration — so it can't show a step the agent didn't really
take. Step captions are generated from the tool name + args, not asked
of the model.

Every run is also logged to disk (results/frontend/, see log_run()) with
full message/usage/cost detail — same record shape scripts/run_comparison.py
writes to results/comparison/, so both sources concatenate cleanly for
analysis regardless of whether a run came from the live app or the batch
script.
"""
import copy
import json
import re
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import plotly.express as px
import plotly.io as pio
from langchain_core.messages import AIMessage, ToolMessage

from model_registry import get_price

RESULTS_DIR = Path(__file__).resolve().parent.parent / "results" / "frontend"

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


def _extract_usage(messages) -> dict:
    """Sums token usage across every AIMessage's `.usage_metadata` — one
    agent turn makes several LLM calls (each ReAct step), so the per-turn
    cost is the sum across all of them, not just the final one. Confirmed
    live that Groq and Gemini both populate `usage_metadata` with the
    same standardized {input_tokens, output_tokens, total_tokens} shape
    (LangChain's normalized field) — Ollama/older provider versions may
    not populate it at all, handled as "unavailable" rather than 0."""
    per_call = []
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.usage_metadata:
            per_call.append({
                "input_tokens": msg.usage_metadata.get("input_tokens", 0),
                "output_tokens": msg.usage_metadata.get("output_tokens", 0),
                "total_tokens": msg.usage_metadata.get("total_tokens", 0),
            })
    if not per_call:
        return {"available": False, "per_call": [], "input_tokens": None, "output_tokens": None, "total_tokens": None}
    return {
        "available": True,
        "per_call": per_call,
        "input_tokens": sum(c["input_tokens"] for c in per_call),
        "output_tokens": sum(c["output_tokens"] for c in per_call),
        "total_tokens": sum(c["total_tokens"] for c in per_call),
    }


def _estimate_cost(provider: str, model: str, usage: dict) -> float | None:
    """USD estimate from usage['input_tokens']/['output_tokens'] and
    model_registry's published per-model pricing. None (not 0) when the
    model isn't priced there — an unpriced model logging as "free" would
    be a silent lie, not a missing feature."""
    if provider == "ollama":
        return 0.0
    if not usage.get("available"):
        return None
    price = get_price(provider, model)
    if price is None:
        return None
    return round(
        usage["input_tokens"] / 1_000_000 * price["input"]
        + usage["output_tokens"] / 1_000_000 * price["output"],
        6,
    )


def _serialize_messages(messages) -> list[dict]:
    """Full-fidelity dump of every message in the run for offline
    analysis — not just the human-readable trace built for the UI. Keeps
    raw content too when it isn't a plain string (Gemini's content-block
    list, incl. thought signatures) so nothing from a real response is
    dropped for the sake of a clean string."""
    out = []
    for msg in messages:
        entry: dict = {"type": type(msg).__name__, "content": _as_text(msg.content)}
        if not isinstance(msg.content, str):
            entry["raw_content"] = msg.content
        if isinstance(msg, AIMessage):
            entry["tool_calls"] = msg.tool_calls or []
            entry["usage_metadata"] = msg.usage_metadata
            entry["model_name"] = msg.response_metadata.get("model_name") if msg.response_metadata else None
        if isinstance(msg, ToolMessage):
            entry["tool_call_id"] = getattr(msg, "tool_call_id", None)
            entry["name"] = getattr(msg, "name", None)
        out.append(entry)
    return out


def _serialize_charts(chart_sink: list) -> list[dict]:
    charts = []
    for fig in chart_sink:
        try:
            charts.append(json.loads(fig.to_json()))
        except Exception as e:
            charts.append({"error": f"failed to serialize chart: {e}"})
    return charts


# Importing streamlit registers its own default Plotly template
# (pio.templates.default = "streamlit"), whose colorway is a set of
# near-black sentinel hex codes (#000001, #000002, ...) — Plotly Express
# bakes the sentinel straight into each trace's marker.color at figure-
# construction time (not just the layout template), and Streamlit's
# frontend JS swaps those sentinels for real theme colors at display
# time in the browser. kaleido has no such frontend, so it renders the
# sentinels literally as solid black. Map each sentinel back to its
# same-index color in the real "plotly" colorway for export.
_SENTINEL_TO_REAL_COLOR = dict(zip(
    pio.templates["streamlit"].layout.colorway,
    pio.templates["plotly"].layout.colorway,
)) if "streamlit" in pio.templates else {}


def _real_color(value):
    return _SENTINEL_TO_REAL_COLOR.get(value, value)


def _export_chart_images(stem_path: Path, chart_sink: list) -> list[str]:
    """Renders each chart to a standalone PNG next to the JSON/txt for a
    run (`{stem}_chart0.png`, `{stem}_chart1.png`, ...) — separate from
    the JSON-embedded Plotly spec (_serialize_charts), for quickly
    browsing/pasting a chart without re-rendering Plotly JSON. PNG over
    PDF: faster to render (kaleido), viewable everywhere without a PDF
    reader; swap format="pdf" here if print-quality vector output is
    needed for the paper later. Returns the filenames written (relative,
    not full paths); never raises — one bad figure just means one fewer
    PNG, not a broken run.

    Works on a deepcopy so the original fig (still in chart_sink, about
    to be displayed live via st.plotly_chart on a later rerun) keeps its
    sentinel colors intact — Streamlit's own theming depends on them.
    """
    names = []
    for i, fig in enumerate(chart_sink):
        png_path = stem_path.parent / f"{stem_path.name}_chart{i}.png"
        try:
            export_fig = copy.deepcopy(fig)
            export_fig.update_layout(template="plotly")
            for trace in export_fig.data:
                marker = getattr(trace, "marker", None)
                if marker is not None and marker.color is not None:
                    if isinstance(marker.color, str):
                        marker.color = _real_color(marker.color)
                    else:
                        marker.color = [_real_color(c) for c in marker.color]
                line = getattr(trace, "line", None)
                if line is not None and line.color is not None:
                    line.color = _real_color(line.color)
            export_fig.write_image(str(png_path), format="png", scale=2)
            names.append(png_path.name)
        except Exception as e:
            print(f"[chat_utils] failed to export chart {i} as PNG (non-fatal): {e}")
    return names


def _format_transcript(record: dict) -> str:
    """Plain-text rendering of a run record — everything a person would
    want to read without opening the JSON: question, answer (narrative +
    hypothesis/evidence for V3), reasoning trace, usage/cost. Defensive
    with .get() throughout since scripts/run_comparison.py's records
    carry a few extra/different keys than the frontend's."""
    lines = [
        f"Question: {record.get('question', '')}",
        "",
        f"Variant: {record.get('variant')} | Provider: {record.get('provider')} | Model: {record.get('model')}",
        f"Timestamp: {record.get('timestamp', '')} | Duration: {record.get('duration_seconds')}s",
        "",
    ]
    if not record.get("success"):
        lines += ["--- FAILED ---", record.get("error") or "(no error message captured)"]
        return "\n".join(lines)

    lines.append("--- Answer ---")
    structured = record.get("structured_response")
    if structured:
        lines.append(structured.get("narrative_answer", ""))
        lines.append("")
        lines.append(f"Hypothesis: {structured.get('hypothesis')} (confidence: {structured.get('confidence')})")
        if structured.get("establishment_name"):
            lines.append(f"Establishment: {structured['establishment_name']}")
        for label, key in [("Supporting", "supporting_evidence"), ("Undermining", "undermining_evidence")]:
            items = structured.get(key) or []
            if items:
                lines.append(f"\n{label} evidence:")
                for e in items:
                    lines.append(f"  - [{e.get('relates_to_concept')}] {e.get('summary')} ({e.get('source_ref')})")
    else:
        lines.append(record.get("output_text") or "")

    lines += ["", "--- Reasoning trace ---", record.get("trace_text") or "(none)"]

    usage = record.get("usage") or {}
    if usage.get("available"):
        cost = record.get("estimated_cost_usd")
        cost_str = f", ~${cost:.4f}" if cost is not None else ", cost unknown (model not in pricing table)"
        lines += ["", f"--- Usage: {usage.get('total_tokens')} tokens{cost_str} ---"]

    return "\n".join(lines)


def log_run(*, variant: str, provider: str, model: str, prompt: str, messages, chart_sink: list,
            candidate_sink: list, trace_text: str, output_text: str, structured_dict: dict | None,
            timeline: list, duration_seconds: float) -> None:
    """Writes one full run record to results/frontend/ — same schema as
    scripts/run_comparison.py's batch output (source differs) so both can
    be loaded together with pandas.read_json(..., lines=True).

    Deliberately swallows every exception: a logging failure must never
    break the actual chat response the user is waiting on. Worst case on
    disk trouble is a missing/partial log file, not a crashed dashboard.
    """
    try:
        usage = _extract_usage(messages)
        record = {
            "source": "frontend",
            "run_id": str(uuid.uuid4())[:8],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "variant": variant,
            "provider": provider,
            "model": model,
            "question": prompt,
            "output_text": output_text,
            "structured_response": structured_dict,
            "trace_text": trace_text,
            "timeline": timeline,
            "messages": _serialize_messages(messages),
            "charts": _serialize_charts(chart_sink),
            "candidate_pool_raw": candidate_sink,
            "duration_seconds": round(duration_seconds, 2),
            "usage": usage,
            "tokens_per_minute": (
                round(usage["total_tokens"] / (duration_seconds / 60), 1)
                if usage.get("available") and duration_seconds > 0 else None
            ),
            "estimated_cost_usd": _estimate_cost(provider, model, usage),
            "success": True,
            "error": None,
        }
        _write_record(record, chart_sink=chart_sink)
    except Exception:
        # Logging is best-effort only — print so it's visible in the
        # Streamlit server's console without ever surfacing to the UI.
        print(f"[chat_utils.log_run] failed to log run (non-fatal): {traceback.format_exc()}")


def log_failed_run(*, variant: str, provider: str, model: str, prompt: str, error: Exception,
                    duration_seconds: float) -> None:
    """Companion to log_run() for the case build_agent()/agent.invoke()
    itself raised (rate limit, bad API key, network error, ...) — the
    dashboards' own try/except already turns this into a graceful chat
    message so the UI never breaks, but that means log_run() is never
    reached (it only runs after a successful invoke). Without this, a
    failed run — arguably the most interesting kind for "don't miss
    anything" — would vanish from the saved data entirely. Same
    best-effort/never-raises contract as log_run()."""
    try:
        record = {
            "source": "frontend", "run_id": str(uuid.uuid4())[:8],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "variant": variant, "provider": provider, "model": model, "question": prompt,
            "output_text": None, "structured_response": None, "trace_text": None,
            "timeline": [], "messages": [], "charts": [], "candidate_pool_raw": [],
            "duration_seconds": round(duration_seconds, 2),
            "usage": {"available": False, "per_call": [], "input_tokens": None, "output_tokens": None, "total_tokens": None},
            "tokens_per_minute": None,
            "estimated_cost_usd": None,
            "success": False,
            "error": f"{type(error).__name__}: {error}",
        }
        _write_record(record)
    except Exception:
        print(f"[chat_utils.log_failed_run] failed to log failed run (non-fatal): {traceback.format_exc()}")


def _write_record(record: dict, chart_sink: list | None = None) -> None:
    """Writes the full JSON record + a line in all_runs.jsonl, plus two
    plain-file sidecars next to it for anyone not working through JSON:
    a .txt transcript (_format_transcript) and one .png per chart
    (_export_chart_images). chart_image_files is computed and folded
    into the record *before* the JSON is written, so the JSON itself
    records which PNGs exist for it."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{record['timestamp'].replace(':', '-')}_{record['variant']}_{record['run_id']}"
    stem_path = RESULTS_DIR / stem

    record["chart_image_files"] = _export_chart_images(stem_path, chart_sink) if chart_sink else []

    (RESULTS_DIR / f"{stem}.json").write_text(json.dumps(record, indent=2, default=str))
    with open(RESULTS_DIR / "all_runs.jsonl", "a") as f:
        f.write(json.dumps(record, default=str) + "\n")
    (RESULTS_DIR / f"{stem}.txt").write_text(_format_transcript(record))


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


def run_agent(agent, prompt: str, chart_sink: list, candidate_sink: list, *,
              variant: str = "unknown", provider: str = "unknown", model: str = "unknown",
              thread_id: str | None = None) -> tuple[str, str]:
    """thread_id is only meaningful for an agent built with a checkpointer
    (agent_memory.py / agent_v2_memory.py / agent_v3_memory.py) — it tells
    LangGraph which persisted conversation to append this turn to and
    replay back into context, so the model sees prior turns without the
    caller having to resend them. None (the default, used by the plain
    agent.py/agent_v2.py/agent_v3.py) omits config entirely, matching the
    original no-memory behavior exactly."""
    start = time.time()
    config = {"configurable": {"thread_id": thread_id}} if thread_id else None
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]}, config=config)
    duration = time.time() - start
    messages = result["messages"]
    output = _as_text(messages[-1].content)
    _ensure_visualization(chart_sink, candidate_sink, messages)
    trace_text = _build_trace(messages)
    log_run(
        variant=variant, provider=provider, model=model, prompt=prompt, messages=messages,
        chart_sink=chart_sink, candidate_sink=candidate_sink, trace_text=trace_text,
        output_text=output, structured_dict=None, timeline=[], duration_seconds=duration,
    )
    return output, trace_text


def run_structured_agent(agent, prompt: str, chart_sink: list, candidate_sink: list, *,
                          variant: str = "unknown", provider: str = "unknown", model: str = "unknown",
                          thread_id: str | None = None):
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

    start = time.time()
    config = {"configurable": {"thread_id": thread_id}} if thread_id else None
    result = agent.invoke({"messages": [{"role": "user", "content": prompt}]}, config=config)
    duration = time.time() - start
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
    trace_text = _build_trace(messages)
    timeline = _build_timeline(messages)
    log_run(
        variant=variant, provider=provider, model=model, prompt=prompt, messages=messages,
        chart_sink=chart_sink, candidate_sink=candidate_sink, trace_text=trace_text,
        output_text=structured.narrative_answer, structured_dict=structured.model_dump(),
        timeline=[asdict(step) for step in timeline], duration_seconds=duration,
    )
    return structured, trace_text, timeline
