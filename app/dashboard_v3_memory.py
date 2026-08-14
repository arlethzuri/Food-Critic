"""Variant 3 + memory: identical to dashboard_v3.py except the chat agent
(agent_v3_memory.py) is given a LangGraph checkpointer, so the
conversation (and the ontology-guided hypothesis/evidence reasoning)
persists across turns within the same browser session. See
agent_memory.py's docstring for the full rationale.

Requires the RAG index to exist first: python3 app/rag/ingest.py

Run alongside the original for a side-by-side comparison (Streamlit
auto-picks the next free port):
    streamlit run app/dashboard_v3.py
    streamlit run app/dashboard_v3_memory.py
"""
import logging
import time
import uuid

# Silence Streamlit's file-watcher warnings from probing transformers'
# lazy submodules (pulled in by sentence-transformers for RAG embeddings)
# that import torchvision, which we don't have/need — harmless, Streamlit
# already catches and continues, this just stops it from spamming the log.
logging.getLogger("streamlit.watcher.local_sources_watcher").setLevel(logging.ERROR)

import streamlit as st
from langgraph.checkpoint.memory import InMemorySaver

from agent_v3_memory import build_agent
from chat_utils import log_failed_run, run_structured_agent
from components.baseline_search import search_baseline
from components.explore_state import clear_chat_results, record_chat_results, resolve_display_rows
from components.filters import render_filters
from components.map_view import render_map
from components.reasoning_view import render_reasoning_view
from components.restaurant_card import render_restaurant_card
from components.results_list import render_results_list
from data_layer import get_connection
from model_picker import render_model_picker
from overview import render_overview
from rag.retriever import load_retriever
from schemas import HypothesisResponse

st.set_page_config(page_title="Food Critic — V3 + Memory", layout="wide")

st.title("Food Critic")
st.caption(
    "Variant 3 + memory: results + map + ReAct agent with RAG over Utah's food-safety "
    "regulation, plus the ontology-guided hypothesis/evidence pipeline "
    "(semantic/ontology.json), with a LangGraph checkpointer so the conversation "
    "persists across turns. Compare against dashboard_v3.py (no memory)."
)

provider, model = render_model_picker("v3")
st.caption(f"Model: {provider} · {model}")


@st.cache_resource
def _connection():
    return get_connection()


@st.cache_resource
def _retriever():
    return load_retriever()


con = _connection()

try:
    retriever = _retriever()
    rag_error = None
except FileNotFoundError as e:
    retriever = None
    rag_error = str(e)

if rag_error:
    st.error(rag_error)

if "v3_selected_gmap_id" not in st.session_state:
    st.session_state.v3_selected_gmap_id = None
if "v3_last_response" not in st.session_state:
    st.session_state.v3_last_response = None
if "v3_last_timeline" not in st.session_state:
    st.session_state.v3_last_timeline = []

# Per-session, in-memory only — a fresh browser session (or hitting "New
# conversation" below) gets a blank checkpointer and a new thread_id, so
# memory never leaks between users/tabs and never survives a real restart.
if "v3_checkpointer" not in st.session_state:
    st.session_state.v3_checkpointer = InMemorySaver()
if "v3_thread_id" not in st.session_state:
    st.session_state.v3_thread_id = str(uuid.uuid4())


def render_evidence_list(items, direction: str):
    if not items:
        st.caption(f"No {direction} evidence.")
        return
    for item in items:
        with st.container(border=True):
            st.markdown(f"**{item.relates_to_concept}**  ·  `{item.source_type}`")
            st.write(item.summary)
            st.caption(item.source_ref)


def render_structured(response: HypothesisResponse):
    st.markdown(response.narrative_answer)
    if response.hypothesis == "none":
        return
    label = response.hypothesis.replace("_", " ")
    est = f" — {response.establishment_name}" if response.establishment_name else ""
    st.info(f"**Hypothesis:** {label}{est}  ·  **confidence:** {response.confidence}")
    st.caption("See the **Reasoning** tab for the map/evidence visualization of this answer.")
    col_support, col_undermine = st.columns(2)
    with col_support:
        st.markdown("**Supporting evidence**")
        render_evidence_list(response.supporting_evidence, "supporting")
    with col_undermine:
        st.markdown("**Undermining evidence**")
        render_evidence_list(response.undermining_evidence, "undermining")


tab_explore, tab_reasoning, tab_overview = st.tabs(["Explore", "Reasoning", "Data overview"])

with tab_explore:
    filter_kwargs = render_filters("v3")
    baseline_rows = search_baseline(con, **filter_kwargs)

    display_rows, chat_prompt = resolve_display_rows("v3", baseline_rows, filter_kwargs)

    col_results, col_map = st.columns([1.2, 3])

    with col_results:
        if chat_prompt:
            cap_col, clear_col = st.columns([5, 1])
            cap_col.caption(f'{len(display_rows)} result(s) for: "{chat_prompt}"')
            if clear_col.button("Clear", key="v3_clear_chat_results"):
                clear_chat_results("v3")
                st.rerun()
        else:
            st.caption(f"{len(display_rows)} result(s)")
        with st.container(height=560):
            clicked = render_results_list(con, display_rows)
        if clicked:
            st.session_state.v3_selected_gmap_id = clicked

    with col_map:
        render_map(display_rows, selected_gmap_id=st.session_state.v3_selected_gmap_id)
        if st.session_state.v3_selected_gmap_id:
            last = st.session_state.v3_last_response
            response_for_card = last if isinstance(last, HypothesisResponse) else None
            render_restaurant_card(con, st.session_state.v3_selected_gmap_id, response_for_card)

    st.divider()
    header_col, button_col = st.columns([5, 1])
    header_col.subheader("Ask about the data or the regulations")
    if button_col.button("New conversation", help="Forget everything asked so far and start a fresh thread."):
        st.session_state.v3_checkpointer = InMemorySaver()
        st.session_state.v3_thread_id = str(uuid.uuid4())
        st.session_state.messages_v3 = []
        st.session_state.v3_last_response = None
        st.session_state.v3_last_timeline = []
        st.rerun()

    if "messages_v3" not in st.session_state:
        st.session_state.messages_v3 = []

    for i, msg in enumerate(st.session_state.messages_v3):
        with st.chat_message(msg["role"]):
            structured = msg.get("structured")
            if isinstance(structured, HypothesisResponse):
                render_structured(structured)
            else:
                st.markdown(msg["content"])
            for j, fig in enumerate(msg.get("charts", [])):
                st.plotly_chart(fig, use_container_width=True, key=f"chat_chart_{i}_{j}")
            if msg.get("trace"):
                with st.expander("Agent reasoning trace"):
                    st.text(msg["trace"])

    # Not wrapped in a container — st.chat_input docks to the bottom of the
    # viewport natively and spans the full app width, per the layout ask.
    prompt = st.chat_input(
        "Ask a question about restaurant safety or food-safety regulations...",
        disabled=retriever is None,
    )
    if prompt and retriever is not None:
        st.session_state.messages_v3.append({"role": "user", "content": prompt, "structured": None})
        with st.chat_message("user"):
            st.markdown(prompt)

        chart_sink, candidate_sink = [], []
        start = time.time()
        with st.chat_message("assistant"), st.spinner("Gathering evidence and forming a hypothesis..."):
            try:
                agent = build_agent(
                    con, chart_sink, candidate_sink, retriever, st.session_state.v3_checkpointer,
                    model=model, provider=provider,
                )
                structured, trace_text, timeline = run_structured_agent(
                    agent, prompt, chart_sink, candidate_sink, variant="v3_memory", provider=provider, model=model,
                    thread_id=st.session_state.v3_thread_id,
                )
            except Exception as e:
                log_failed_run(variant="v3_memory", provider=provider, model=model, prompt=prompt, error=e, duration_seconds=time.time() - start)
                structured = (
                    f"Something went wrong talking to the model: {e}\n\n"
                    "Check `app/.env` — is `LLM_PROVIDER` set and the matching API key "
                    "present (or, for Ollama, is `ollama serve` running)? See app/README.md."
                )
                trace_text = ""
                timeline = []

        if isinstance(structured, HypothesisResponse):
            content_for_history = structured.narrative_answer
            st.session_state.v3_last_response = structured
            st.session_state.v3_last_timeline = timeline
        else:
            content_for_history = structured

        record_chat_results("v3", prompt, candidate_sink)

        st.session_state.messages_v3.append({
            "role": "assistant",
            "content": content_for_history,
            "structured": structured if isinstance(structured, HypothesisResponse) else None,
            "charts": chart_sink,
            "trace": trace_text,
        })
        st.rerun()

with tab_reasoning:
    last = st.session_state.v3_last_response
    last_timeline = st.session_state.v3_last_timeline
    # Gate on there being an actual trace to show, not on the hypothesis
    # classification — "top 10 by X" is a legitimate hypothesis="none"
    # (it's not a claim about one establishment's trustworthiness, which
    # is what the hypothesis vocabulary covers) but it still ran real
    # tool calls worth visualizing.
    if isinstance(last, HypothesisResponse) and (last.candidate_pool or last_timeline):
        render_reasoning_view(last, last_timeline)
    else:
        st.info(
            "No reasoning to show yet. Ask a question in the **Explore** tab's chat "
            "— any answer that searches or ranks establishments will show its "
            "map-step and evidence visualizations here."
        )

with tab_overview:
    render_overview(con)
