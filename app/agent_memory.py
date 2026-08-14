"""Variant 1 with LangGraph memory: identical to agent.py except
create_agent is given a checkpointer, so the conversation persists across
turns within the same thread_id instead of each question starting from a
blank slate. See chat_utils.run_agent's thread_id param (how a turn gets
tied to a persisted conversation) and dashboard_memory.py (how the
checkpointer + thread_id get created and kept alive for a browser
session).

Reuses agent.py's SYSTEM_PROMPT verbatim (imported, not copy-pasted) so
this stays a pure "add memory" comparison against the original — the
prompt can't drift between the two independently.
"""
from langchain.agents import create_agent

from agent import SYSTEM_PROMPT
from llm import get_llm
from tools import CHARTING_POLICY, GROUNDING_POLICY, make_tools


def build_agent(con, chart_sink: list, candidate_sink: list, checkpointer,
                 model: str | None = None, provider: str | None = None, verbose: bool = False):
    llm = get_llm(model, provider)
    tools = make_tools(con, chart_sink, candidate_sink)
    system_prompt = SYSTEM_PROMPT.format(grounding_policy=GROUNDING_POLICY, charting_policy=CHARTING_POLICY)
    return create_agent(llm, tools, system_prompt=system_prompt, checkpointer=checkpointer, debug=verbose)
