"""Variant 1 dashboard: results list + filters + map (View 1) + a chat box
backed by the ReAct agent in agent.py. No RAG, no ontology — no Reasoning
tab (that's Variant 3 only).

Run with: streamlit run app/dashboard.py
"""
import logging
import time

# Silence Streamlit's file-watcher warnings from probing transformers'
# lazy submodules (pulled in by sentence-transformers for RAG embeddings)
# that import torchvision, which we don't have/need — harmless, Streamlit
# already catches and continues, this just stops it from spamming the log.
logging.getLogger("streamlit.watcher.local_sources_watcher").setLevel(logging.ERROR)

import streamlit as st

from agent import build_agent
from chat_utils import log_failed_run, run_agent
from components.baseline_search import search_baseline
from components.filters import render_filters
from components.map_view import render_map
from components.restaurant_card import render_restaurant_card
from components.results_list import render_results_list
from data_layer import get_connection
from model_picker import render_model_picker
from overview import render_overview

st.set_page_config(page_title="Food Critic — V1", layout="wide")

st.title("Food Critic")
st.caption(
    "Variant 1: results + map + ReAct agent over inspection/violation data only. "
    "No RAG, no ontology-guided reasoning in this variant."
)

provider, model = render_model_picker("v1")
st.caption(f"Model: {provider} · {model}")


@st.cache_resource
def _connection():
    return get_connection()


con = _connection()

tab_explore, tab_overview = st.tabs(["Explore", "Data overview"])

with tab_explore:
    filter_kwargs = render_filters("v1")
    baseline_rows = search_baseline(con, **filter_kwargs)

    if "v1_selected_gmap_id" not in st.session_state:
        st.session_state.v1_selected_gmap_id = None

    col_results, col_map = st.columns([1.2, 3])

    with col_results:
        st.caption(f"{len(baseline_rows)} result(s)")
        with st.container(height=560):
            clicked = render_results_list(baseline_rows)
        if clicked:
            st.session_state.v1_selected_gmap_id = clicked

    with col_map:
        render_map(baseline_rows, selected_gmap_id=st.session_state.v1_selected_gmap_id)
        if st.session_state.v1_selected_gmap_id:
            render_restaurant_card(con, st.session_state.v1_selected_gmap_id)

    st.divider()
    st.subheader("Ask about the data")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for fig in msg.get("charts", []):
                st.plotly_chart(fig, use_container_width=True)
            if msg.get("trace"):
                with st.expander("Agent reasoning trace"):
                    st.text(msg["trace"])

    # Not wrapped in a container — st.chat_input docks to the bottom of the
    # viewport natively and spans the full app width, per the layout ask.
    prompt = st.chat_input("Ask a question about restaurant safety...")
    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})

        chart_sink, candidate_sink = [], []
        start = time.time()
        try:
            agent = build_agent(con, chart_sink, candidate_sink, model=model, provider=provider)
            output, trace_text = run_agent(agent, prompt, chart_sink, candidate_sink, variant="v1", provider=provider, model=model)
        except Exception as e:
            log_failed_run(variant="v1", provider=provider, model=model, prompt=prompt, error=e, duration_seconds=time.time() - start)
            output = (
                f"Something went wrong talking to the model: {e}\n\n"
                "Check `app/.env` — is `LLM_PROVIDER` set and the matching API key "
                "present (or, for Ollama, is `ollama serve` running)? See app/README.md."
            )
            trace_text = ""

        st.session_state.messages.append({
            "role": "assistant",
            "content": output,
            "charts": chart_sink,
            "trace": trace_text,
        })
        st.rerun()

with tab_overview:
    render_overview(con)
