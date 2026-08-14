"""Variant 1 + memory: identical to dashboard.py except the chat agent
(agent_memory.py) is given a LangGraph checkpointer, so it remembers
prior turns within the same browser session instead of starting fresh
on every question — see agent_memory.py and chat_utils.run_agent's
thread_id param for how that's wired.

Run alongside the original for a side-by-side comparison (Streamlit
auto-picks the next free port):
    streamlit run app/dashboard.py
    streamlit run app/dashboard_memory.py
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

from agent_memory import build_agent
from chat_utils import log_failed_run, run_agent
from components.baseline_search import search_baseline
from components.explore_state import clear_chat_results, record_chat_results, resolve_display_rows
from components.filters import render_filters
from components.map_view import render_map
from components.restaurant_card import render_restaurant_card
from components.results_list import render_results_list
from data_layer import get_connection
from model_picker import render_model_picker
from overview import render_overview

st.set_page_config(page_title="Food Critic — V1 + Memory", layout="wide")

st.title("Food Critic")
st.caption(
    "Variant 1 + memory: results + map + ReAct agent over inspection/violation data only, "
    "with a LangGraph checkpointer so the conversation persists across turns. "
    "Compare against dashboard.py (no memory) to see the difference."
)

provider, model = render_model_picker("v1")
st.caption(f"Model: {provider} · {model}")


@st.cache_resource
def _connection():
    return get_connection()


con = _connection()

# Per-session, in-memory only — a fresh browser session (or hitting "New
# conversation" below) gets a blank checkpointer and a new thread_id, so
# memory never leaks between users/tabs and never survives a real restart.
if "v1_checkpointer" not in st.session_state:
    st.session_state.v1_checkpointer = InMemorySaver()
if "v1_thread_id" not in st.session_state:
    st.session_state.v1_thread_id = str(uuid.uuid4())

tab_explore, tab_overview = st.tabs(["Explore", "Data overview"])

with tab_explore:
    filter_kwargs = render_filters("v1")
    baseline_rows = search_baseline(con, **filter_kwargs)

    if "v1_selected_gmap_id" not in st.session_state:
        st.session_state.v1_selected_gmap_id = None

    display_rows, chat_prompt = resolve_display_rows("v1", baseline_rows, filter_kwargs)

    col_results, col_map = st.columns([1.2, 3])

    with col_results:
        if chat_prompt:
            cap_col, clear_col = st.columns([5, 1])
            cap_col.caption(f'{len(display_rows)} result(s) for: "{chat_prompt}"')
            if clear_col.button("Clear", key="v1_clear_chat_results"):
                clear_chat_results("v1")
                st.rerun()
        else:
            st.caption(f"{len(display_rows)} result(s)")
        with st.container(height=560):
            clicked = render_results_list(con, display_rows)
        if clicked:
            st.session_state.v1_selected_gmap_id = clicked

    with col_map:
        render_map(display_rows, selected_gmap_id=st.session_state.v1_selected_gmap_id)
        if st.session_state.v1_selected_gmap_id:
            render_restaurant_card(con, st.session_state.v1_selected_gmap_id)

    st.divider()
    header_col, button_col = st.columns([5, 1])
    header_col.subheader("Ask about the data")
    if button_col.button("New conversation", help="Forget everything asked so far and start a fresh thread."):
        st.session_state.v1_checkpointer = InMemorySaver()
        st.session_state.v1_thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for i, msg in enumerate(st.session_state.messages):
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for j, fig in enumerate(msg.get("charts", [])):
                st.plotly_chart(fig, use_container_width=True, key=f"chat_chart_{i}_{j}")
            if msg.get("trace"):
                with st.expander("Agent reasoning trace"):
                    st.text(msg["trace"])

    # Not wrapped in a container — st.chat_input docks to the bottom of the
    # viewport natively and spans the full app width, per the layout ask.
    prompt = st.chat_input("Ask a question about restaurant safety...")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        chart_sink, candidate_sink = [], []
        start = time.time()
        with st.chat_message("assistant"), st.spinner("Querying the data and building an answer..."):
            try:
                agent = build_agent(
                    con, chart_sink, candidate_sink, st.session_state.v1_checkpointer,
                    model=model, provider=provider,
                )
                output, trace_text = run_agent(
                    agent, prompt, chart_sink, candidate_sink, variant="v1_memory", provider=provider, model=model,
                    thread_id=st.session_state.v1_thread_id,
                )
            except Exception as e:
                log_failed_run(variant="v1_memory", provider=provider, model=model, prompt=prompt, error=e, duration_seconds=time.time() - start)
                output = (
                    f"Something went wrong talking to the model: {e}\n\n"
                    "Check `app/.env` — is `LLM_PROVIDER` set and the matching API key "
                    "present (or, for Ollama, is `ollama serve` running)? See app/README.md."
                )
                trace_text = ""

        record_chat_results("v1", prompt, candidate_sink)

        st.session_state.messages.append({
            "role": "assistant",
            "content": output,
            "charts": chart_sink,
            "trace": trace_text,
        })
        st.rerun()

with tab_overview:
    render_overview(con)
