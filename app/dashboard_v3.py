"""Variant 3 dashboard: same fixed safety overview, but the chat agent's
final answer is structured (schemas.HypothesisResponse) rather than free
text — a fixed-vocabulary hypothesis plus typed, ontology-tagged evidence
for and against it (semantic/gen_ontology.json). This panel is the actual
reasoning-visualization payoff: instead of prose the user has to trust,
each claim is a discrete, inspectable item citing where it came from.

Requires the RAG index to exist first: python3 app/rag/ingest.py
Run with: streamlit run app/dashboard_v3.py
"""
import logging

# Silence Streamlit's file-watcher warnings from probing transformers'
# lazy submodules (pulled in by sentence-transformers for RAG embeddings)
# that import torchvision, which we don't have/need — harmless, Streamlit
# already catches and continues, this just stops it from spamming the log.
logging.getLogger("streamlit.watcher.local_sources_watcher").setLevel(logging.ERROR)

import streamlit as st

from agent_v3 import build_agent
from chat_utils import run_structured_agent
from data_layer import get_connection
from model_picker import render_model_picker
from overview import render_overview
from rag.retriever import load_retriever
from schemas import HypothesisResponse

st.set_page_config(page_title="Food Critic — SLC Safety Overview (+Ontology)", layout="wide")

provider, model = render_model_picker("v3")


@st.cache_resource
def _connection():
    return get_connection()


@st.cache_resource
def _retriever():
    return load_retriever()


con = _connection()

st.title("Food Critic — SLC Restaurant Safety Overview")
st.caption(
    "Variant 3: ReAct agent over inspection/violation data + RAG over Utah's food-safety "
    "regulation, plus an ontology-guided hypothesis/evidence pipeline "
    "(semantic/gen_ontology.json) — every recommendation or warning is tagged with a fixed "
    "hypothesis type and evidence traced back to specific tool calls. Still no review data (Yelp)."
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

    col_support, col_undermine = st.columns(2)
    with col_support:
        st.markdown("**Supporting evidence**")
        render_evidence_list(response.supporting_evidence, "supporting")
    with col_undermine:
        st.markdown("**Undermining evidence**")
        render_evidence_list(response.undermining_evidence, "undermining")


if "messages_v3" not in st.session_state:
    st.session_state.messages_v3 = []

for msg in st.session_state.messages_v3:
    with st.chat_message(msg["role"]):
        structured = msg.get("structured")
        if isinstance(structured, HypothesisResponse):
            render_structured(structured)
        else:
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
    st.session_state.messages_v3.append({"role": "user", "content": prompt, "structured": None})
    with st.chat_message("user"):
        st.markdown(prompt)

    chart_sink = []
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                agent = build_agent(con, chart_sink, retriever, model=model, provider=provider)
                structured, trace_text = run_structured_agent(agent, prompt)
            except Exception as e:
                structured = (
                    f"Something went wrong talking to the model: {e}\n\n"
                    "Check `app/.env` — is `LLM_PROVIDER` set and the matching API key "
                    "present (or, for Ollama, is `ollama serve` running)? See app/README.md."
                )
                trace_text = ""

        if isinstance(structured, HypothesisResponse):
            render_structured(structured)
            content_for_history = structured.narrative_answer
        else:
            st.markdown(structured)
            content_for_history = structured

        for fig in chart_sink:
            st.plotly_chart(fig, use_container_width=True)

        if trace_text:
            with st.expander("Agent reasoning trace"):
                st.text(trace_text)

    st.session_state.messages_v3.append({
        "role": "assistant",
        "content": content_for_history,
        "structured": structured if isinstance(structured, HypothesisResponse) else None,
        "charts": chart_sink,
        "trace": trace_text,
    })
