"""Variant 2 with LangGraph memory: identical to agent_v2.py except
create_agent is given a checkpointer, so the conversation persists across
turns within the same thread_id. See agent_memory.py's docstring for the
full rationale — same pattern, applied to the +RAG variant.

Reuses agent_v2.py's SYSTEM_PROMPT verbatim (imported, not copy-pasted).
"""
from langchain.agents import create_agent

from agent_v2 import SYSTEM_PROMPT
from llm import get_llm
from rag_tool import make_rag_tool
from tools import CHARTING_POLICY, GROUNDING_POLICY, make_tools


def build_agent(con, chart_sink: list, candidate_sink: list, retriever, checkpointer,
                 model: str | None = None, provider: str | None = None, verbose: bool = False):
    llm = get_llm(model, provider)
    tools = make_tools(con, chart_sink, candidate_sink) + [make_rag_tool(retriever)]
    system_prompt = SYSTEM_PROMPT.format(grounding_policy=GROUNDING_POLICY, charting_policy=CHARTING_POLICY)
    return create_agent(llm, tools, system_prompt=system_prompt, checkpointer=checkpointer, debug=verbose)
