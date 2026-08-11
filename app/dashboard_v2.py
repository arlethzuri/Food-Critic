"""Variant 2 dashboard: same results list + filters + map (View 1) as
Variant 1, but the chat agent also has RAG access to Utah's food-safety
regulation and SLC county's inspection-process page (app/rag/). No
ontology-guided reasoning view / Reasoning tab — that's Variant 3 only.

Requires the RAG index to exist first: python3 app/rag/ingest.py
Run with: streamlit run app/dashboard_v2.py
"""
import logging

# Silence Streamlit's file-watcher warnings from probing transformers'
# lazy submodules (pulled in by sentence-transformers for RAG embeddings)
# that import torchvision, which we don't have/need — harmless, Streamlit
# already catches and continues, this just stops it from spamming the log.
logging.getLogger("streamlit.watcher.local_sources_watcher").setLevel(logging.ERROR)

import streamlit as st

from agent_v2 import build_agent
from chat_utils import run_agent
from components.baseline_search import search_baseline
from components.filters import render_filters
from components.map_view import render_map
from components.restaurant_card import render_restaurant_card
from components.results_list import render_results_list
from data_layer import get_connection
from model_picker import render_model_picker
from overview import render_overview
from rag.retriever import load_retriever

st.set_page_config(page_title="Food Critic — V2 (+RAG)", layout="wide")

st.title("Food Critic")
st.caption(
    "Variant 2: results + map + ReAct agent over inspection/violation data, "
    "plus RAG over Utah's R392-100 Food Service Sanitation Rule and SLC "
    "county's inspection-process page."
)

provider, model = render_model_picker("v2")
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

tab_explore, tab_overview = st.tabs(["Explore", "Data overview"])

with tab_explore:
    filter_kwargs = render_filters("v2")
    baseline_rows = search_baseline(con, **filter_kwargs)

    if "v2_selected_gmap_id" not in st.session_state:
        st.session_state.v2_selected_gmap_id = None

    col_results, col_map = st.columns([1.2, 3])

    with col_results:
        st.caption(f"{len(baseline_rows)} result(s)")
        with st.container(height=560):
            clicked = render_results_list(baseline_rows)
        if clicked:
            st.session_state.v2_selected_gmap_id = clicked

    with col_map:
        render_map(baseline_rows, selected_gmap_id=st.session_state.v2_selected_gmap_id)
        if st.session_state.v2_selected_gmap_id:
            render_restaurant_card(con, st.session_state.v2_selected_gmap_id)

    st.divider()
    st.subheader("Ask about the data or the regulations")

    if "messages_v2" not in st.session_state:
        st.session_state.messages_v2 = []

    for msg in st.session_state.messages_v2:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            for fig in msg.get("charts", []):
                st.plotly_chart(fig, use_container_width=True)
            if msg.get("trace"):
                with st.expander("Agent reasoning trace"):
                    st.text(msg["trace"])

    # Not wrapped in a container — st.chat_input docks to the bottom of the
    # viewport natively and spans the full app width, per the layout ask.
    prompt = st.chat_input(
        "Ask about restaurant safety or food-safety regulations...",
        disabled=retriever is None,
    )
    if prompt and retriever is not None:
        st.session_state.messages_v2.append({"role": "user", "content": prompt})

        chart_sink, candidate_sink = [], []
        try:
            agent = build_agent(con, chart_sink, candidate_sink, retriever, model=model, provider=provider)
            output, trace_text = run_agent(agent, prompt, chart_sink, candidate_sink)
        except Exception as e:
            output = (
                f"Something went wrong talking to the model: {e}\n\n"
                "Check `app/.env` — is `LLM_PROVIDER` set and the matching API key "
                "present (or, for Ollama, is `ollama serve` running)? See app/README.md."
            )
            trace_text = ""

        st.session_state.messages_v2.append({
            "role": "assistant",
            "content": output,
            "charts": chart_sink,
            "trace": trace_text,
        })
        st.rerun()

with tab_overview:
    render_overview(con)
