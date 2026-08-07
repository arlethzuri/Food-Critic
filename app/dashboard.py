"""Variant 1 dashboard: fixed safety overview (computed directly, not by
the agent) + a chat box backed by the ReAct agent in agent.py.

Run with: streamlit run app/dashboard.py
"""
import logging

# Silence Streamlit's file-watcher warnings from probing transformers'
# lazy submodules (pulled in by sentence-transformers for RAG embeddings)
# that import torchvision, which we don't have/need — harmless, Streamlit
# already catches and continues, this just stops it from spamming the log.
logging.getLogger("streamlit.watcher.local_sources_watcher").setLevel(logging.ERROR)

import streamlit as st

from agent import build_agent
from chat_utils import run_agent
from data_layer import get_connection
from model_picker import render_model_picker
from overview import render_overview

st.set_page_config(page_title="Food Critic — SLC Safety Overview", layout="wide")

provider, model = render_model_picker("v1")


@st.cache_resource
def _connection():
    return get_connection()


con = _connection()

st.title("Food Critic — SLC Restaurant Safety Overview")
st.caption(
    "Variant 1: ReAct agent over inspection/violation data only. "
    "No review data (Yelp) or regulatory RAG in this variant yet."
)
st.caption(f"Model: {provider} · {model}")

render_overview(con)

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

prompt = st.chat_input("Ask a question about restaurant safety...")
if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    chart_sink = []
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                agent = build_agent(con, chart_sink, model=model, provider=provider)
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

    st.session_state.messages.append({
        "role": "assistant",
        "content": output,
        "charts": chart_sink,
        "trace": trace_text,
    })
