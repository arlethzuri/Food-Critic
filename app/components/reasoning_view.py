"""View 2A/2B — the reasoning/evidence view. One screen, two focal states
per the sketch (2A: map-centric step reasoning: a Timeline scrubber that
re-renders the map at whichever tool-call step is selected; 2B:
evidence-cards-centric: one glyph per candidate showing why it's in the
answer). The Timeline scrubber switches between them, rather than the
earlier true-animation idea — matches the sketch's own written fallback
("let user scroll thru agent's visual reasoning, could be instead").

Colors are the dataviz skill's reference palette (semantic/../references
not vendored here — see palette.md): status colors for the evidence
glyph (a value-vs-threshold judgment call), the fixed 8-slot categorical
order for ViolationType, plain blue/gray for the map's in/out states
(not a status judgment, just membership in a step's result set).

Hesitation carried over from the plan: the evidence glyph is a bespoke
chart, not an off-the-shelf form — treat this as a first draft to iterate
on, not a settled design.
"""
import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from chat_utils import ReasoningStep
from schemas import CandidatePoolItem, HypothesisResponse

ROOT = Path(__file__).resolve().parent.parent.parent
PERCENTILES = json.loads((ROOT / "semantic" / "percentiles.json").read_text(encoding="utf-8"))

BLUE = "#2a78d6"
GRAY = "#9a9990"
STATUS_GOOD = "#0ca30c"
STATUS_WARNING = "#fab219"
STATUS_CRITICAL = "#d03b3b"

# Where each criterion's "good" bar sits between the loose (p25/p10) and
# exact (p90/p75) percentile bounds in percentiles.json — used to be a
# user-adjustable Strictness slider; fixed at its old default (0.7) since
# the slider's effect wasn't legible to users, but the underlying
# percentile-based bounds are still real data, not invented numbers.
_THRESHOLD_POSITION = 0.7


def _scale_threshold(low: float, high: float) -> float:
    return low + _THRESHOLD_POSITION * (high - low)


def render_reasoning_view(response: HypothesisResponse, timeline: list[ReasoningStep]):
    if response.hypothesis == "none":
        st.caption("Plain data lookup — no specific hypothesis formed, showing the tool-call trace below.")
    else:
        st.caption(f"Hypothesis: **{response.hypothesis.replace('_', ' ')}**  ·  confidence: {response.confidence}")

    map_steps = [s for s in timeline if s.kind == "map" and s.rows]
    if not map_steps and response.candidate_pool:
        # No search_establishments step captured directly (e.g. the agent
        # answered via a hand-written run_sql query) — fall back to a
        # single static map of the final candidate pool rather than
        # showing nothing. candidate_pool is always ground-truth (see
        # chat_utils.run_structured_agent), so this is never fabricated.
        fallback_rows = [c.model_dump() for c in response.candidate_pool]
        map_steps = [
            ReasoningStep(
                index=0, kind="map", tool_name="candidate_pool", tool_args={},
                caption="Final candidate set (no step-by-step trace available)",
                rows=fallback_rows,
            )
        ]

    if map_steps:
        step_idx = st.select_slider(
            "Timeline", options=list(range(len(map_steps))),
            format_func=lambda i: map_steps[i].caption,
            value=len(map_steps) - 1,
        )
        _render_map_step(map_steps[step_idx])
    else:
        st.info("No map-producing steps in this answer's tool-call trace.")

    other_steps = [s for s in timeline if s.kind != "map"]
    if other_steps:
        with st.expander(f"Other reasoning steps ({len(other_steps)})"):
            for step in other_steps:
                icon = {"citation": "📖", "classification": "🏷️", "sql": "🔎", "chart": "📊", "inspection_history": "🗂️"}.get(step.kind, "•")
                st.write(f"{icon} {step.caption}")

    st.markdown("**Evidence — why each candidate is in this answer**")
    ranked = _rank_candidates(response.candidate_pool)
    if not ranked:
        st.caption("No candidates in this answer's pool.")
        return

    cols = st.columns(min(3, len(ranked)))
    for i, candidate in enumerate(ranked[:6]):
        with cols[i % len(cols)]:
            _render_evidence_glyph(candidate)


def _render_map_step(step: ReasoningStep):
    df = pd.DataFrame(step.rows).dropna(subset=["latitude", "longitude"])
    if df.empty:
        st.info("This step's results have no known coordinates.")
        return
    fig = px.scatter_map(
        df, lat="latitude", lon="longitude", hover_name="name",
        hover_data={"avg_rating": ":.1f", "latitude": False, "longitude": False},
        color_discrete_sequence=[BLUE], zoom=10, height=380,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
    st.plotly_chart(fig, use_container_width=True, key=f"map_step_{step.index}")
    st.caption(step.caption)


def criteria_status(candidate: CandidatePoolItem) -> list[tuple[str, float, float, str]]:
    """One (label, value, target, status) row per criterion with a real
    value, status in {good, warning, critical} against a fixed
    percentile-based bound (see _THRESHOLD_POSITION). Shared by the
    ranker and the glyph so a candidate's rank always matches what its
    own glyph shows — ranking on a different formula than the visible
    colors would be misleading."""
    r = PERCENTILES["avg_rating"]
    n = PERCENTILES["num_of_reviews"]
    rating_bar = _scale_threshold(r["p25"], r["p90"])
    review_bar = _scale_threshold(n["p10"], n["p75"])

    def status(value: float, target: float) -> str:
        if value >= target:
            return "good"
        if value >= target * 0.85:
            return "warning"
        return "critical"

    rows = []
    if candidate.avg_rating is not None:
        rows.append(("Rating", candidate.avg_rating, rating_bar, status(candidate.avg_rating, rating_bar)))
    if candidate.num_of_reviews is not None:
        rows.append(("Reviews", candidate.num_of_reviews, review_bar, status(candidate.num_of_reviews, review_bar)))
    return rows


def _rank_candidates(pool: list[CandidatePoolItem]) -> list[CandidatePoolItem]:
    """Best-first by (criteria passed, then margin above target) — ties
    the ranking to the same pass/fail judgment the glyph renders, so
    order and color never disagree."""
    _STATUS_RANK = {"good": 2, "warning": 1, "critical": 0}

    def score(c: CandidatePoolItem) -> tuple[int, float]:
        rows = criteria_status(c)
        if not rows:
            return (0, 0.0)
        passed = sum(_STATUS_RANK[status] for *_, status in rows)
        margin = sum((value - target) / max(target, 1e-6) for _, value, target, _ in rows)
        return (passed, margin)

    return sorted(pool, key=score, reverse=True)


def _render_evidence_glyph(candidate: CandidatePoolItem):
    STATUS_COLOR = {"good": STATUS_GOOD, "warning": STATUS_WARNING, "critical": STATUS_CRITICAL}
    with st.container(border=True):
        st.markdown(f"**{candidate.name}**")
        if candidate.address:
            # Street only (address is "Name, Street, City, ST ZIP") — several
            # chains (e.g. Apollo Burger) have multiple locations, so the
            # bare name alone doesn't distinguish these cards.
            street = candidate.address.split(",")[1].strip() if candidate.address.count(",") >= 2 else candidate.address
            st.caption(street)

        rows = criteria_status(candidate)
        if candidate.distance_mi is not None:
            rows.append(("Distance (mi)", candidate.distance_mi, None, "good"))

        fig = go.Figure()
        for i, (label, value, target, row_status) in enumerate(rows):
            fig.add_trace(go.Scatter(
                x=[value], y=[label], mode="markers+text",
                marker=dict(size=14, color=STATUS_COLOR[row_status]),
                text=[f"{value:.1f}"], textposition="middle right",
                showlegend=False,
            ))
            if target is not None:
                fig.add_shape(
                    type="line", x0=target, x1=target, y0=i - 0.4, y1=i + 0.4,
                    line=dict(color=GRAY, width=2, dash="dot"),
                )
        fig.update_layout(
            height=120 + 30 * len(rows),
            margin=dict(l=70, r=40, t=10, b=10),
            xaxis=dict(showgrid=False, zeroline=False),
            yaxis=dict(showgrid=False),
        )
        st.plotly_chart(fig, use_container_width=True, key=f"glyph_{candidate.gmap_id}")

        if candidate.slchd_establishment_key:
            if candidate.inspection_score is not None:
                score_status = "🟢" if candidate.inspection_score <= 3 else (
                    "🟡" if candidate.inspection_score <= 10 else "🔴"
                )
                st.caption(f"{score_status} Most recent inspection score: {candidate.inspection_score:.0f}")
            else:
                st.caption("Has SLCHD inspection history (score not pulled for this answer).")
            if candidate.critical_violation_count is not None:
                st.caption(
                    f"⚠️ {candidate.critical_violation_count} critical / "
                    f"{candidate.total_violation_count} total violations on record"
                )
        else:
            st.caption("⚪ No matched SLCHD inspection history.")
