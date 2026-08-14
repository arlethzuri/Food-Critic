"""Variant 3 with LangGraph memory: identical to agent_v3.py except
create_agent is given a checkpointer, so the conversation (and the
ontology-guided hypothesis/evidence reasoning) persists across turns
within the same thread_id. See agent_memory.py's docstring for the full
rationale — same pattern, applied to the +RAG+ontology variant.

Reuses agent_v3.py's SYSTEM_PROMPT verbatim (imported, not copy-pasted).
"""
from langchain.agents import create_agent

from agent_v3 import SYSTEM_PROMPT
from llm import get_llm
from ontology import hypothesis_guidance_text, make_classify_tool
from rag_tool import make_rag_tool
from schemas import HypothesisResponse
from tools import CHARTING_POLICY, GROUNDING_POLICY, make_tools


def build_agent(con, chart_sink: list, candidate_sink: list, retriever, checkpointer,
                 model: str | None = None, provider: str | None = None, verbose: bool = False):
    llm = get_llm(model, provider)
    tools = make_tools(con, chart_sink, candidate_sink) + [make_rag_tool(retriever), make_classify_tool()]
    system_prompt = SYSTEM_PROMPT.format(
        grounding_policy=GROUNDING_POLICY,
        charting_policy=CHARTING_POLICY,
        hypothesis_guidance=hypothesis_guidance_text(),
    )
    return create_agent(
        llm,
        tools,
        system_prompt=system_prompt,
        response_format=HypothesisResponse,
        checkpointer=checkpointer,
        debug=verbose,
    )
