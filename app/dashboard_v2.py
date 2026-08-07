"""Variant 2 dashboard: same fixed safety overview as Variant 1, but the
chat agent also has RAG access to Utah's food-safety regulation and SLC
county's inspection-process page (app/rag/). Compare against dashboard.py
(Variant 1) for RQ1.

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
from data_layer import get_connection
from model_picker import render_model_picker
from overview import render_overview
from rag.retriever import load_retriever

st.set_page_config(page_title="Food Critic — SLC Safety Overview (+RAG)", layout="wide")

provider, model = render_model_picker("v2")


@st.cache_resource
def _connection():
    return get_connection()


@st.cache_resource
def _retriever():
    return load_retriever()


con = _connection()

st.title("Food Critic — SLC Restaurant Safety Overview")
st.caption(
    "Variant 2: ReAct agent over inspection/violation data + RAG over Utah's "
    "R392-100 Food Service Sanitation Rule and SLC county's inspection-process page. "
    "Still no review data (Yelp)."
)
st.caption(f"Model: {provider} · {model}")

render_overview(con)

st.divider()
st.subheader("Ask about the data or the regulations")

try:
    retriever = _retriever()
    rag_error = None
except FileNotFoundError as e:
    retriever = None
    rag_error = str(e)

if rag_error:
    st.error(rag_error)

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

prompt = st.chat_input(
    "Ask a question about restaurant safety or food-safety regulations...",
    disabled=retriever is None,
)
if prompt and retriever is not None:
    st.session_state.messages_v2.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    chart_sink = []
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                agent = build_agent(con, chart_sink, retriever, model=model, provider=provider)
                output, trace_text = run_agent(agent, prompt)
            except Exception as e:
                output = (
                    f"Something went wrong talking to the model: {e}\n\n"
                    "Check `app/.env` — is `LLM_PROVIDER` set and the matching API key "
                    "present (or, for Ollama, is `ollama serve` running)? See app/README.md."
                )
                trace_text = ""

        st.markdown(output)
        for fig in chart_sink:
            st.plotly_chart(fig, use_container_width=True)

        if trace_text:
            with st.expander("Agent reasoning trace"):
                st.text(trace_text)

    st.session_state.messages_v2.append({
        "role": "assistant",
        "content": output,
        "charts": chart_sink,
        "trace": trace_text,
    })
