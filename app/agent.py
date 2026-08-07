"""Variant 1: ReAct-style agent (reason + act in a tool-calling loop) over
the merged CSV only — no RAG, no ontology, no review data. This is meant
to double as the RQ1 baseline condition: whatever variants 2/3 add later,
this one gets compared against.

Uses a hosted free-tier model (Groq or Google) or a local Ollama model,
picked via `app/.env` — see llm.py and app/README.md. Built on LangChain's
create_agent (native tool-calling loop, not text-parsed ReAct) since that
API replaced the classic AgentExecutor/create_react_agent in LangChain
1.0, and hosted models follow native tool-calling far more reliably than
a text Thought/Action/Observation scaffold anyway.
"""
from langchain.agents import create_agent

from llm import get_llm
from tools import make_tools

SYSTEM_PROMPT = """\
You are a food-safety data analyst answering questions about restaurants \
in Salt Lake County using ONLY the `inspections` table (SLC health \
inspection + violation records). You have no review data and no \
regulatory text in this variant — ground every claim in a run_sql result, \
never guess a number. Call get_schema first if you're unsure what's \
queryable. When a question calls for a visual, use plot_chart in addition \
to (not instead of) explaining the finding in words, and cite the actual \
numbers you found in your final answer."""


def build_agent(con, chart_sink: list, model: str | None = None, provider: str | None = None, verbose: bool = False):
    llm = get_llm(model, provider)
    tools = make_tools(con, chart_sink)
    return create_agent(llm, tools, system_prompt=SYSTEM_PROMPT, debug=verbose)
