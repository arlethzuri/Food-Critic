"""Variant 2: ReAct-style agent (reason + act in a tool-calling loop) with
both CSV data access (tools.py) and RAG retrieval over Utah's R392-100
Food Service Sanitation Rule and SLC county's inspection-process page
(rag_tool.py / app/rag/). Compared against Variant 1's data-only baseline
for RQ1. See agent.py's docstring for why this is create_agent (native
tool-calling) rather than the old text-parsed ReAct AgentExecutor.
"""
from langchain.agents import create_agent

from llm import get_llm
from rag_tool import make_rag_tool
from tools import make_tools

SYSTEM_PROMPT = """\
You are a food-safety data analyst answering questions about restaurants \
in Salt Lake County. You have two grounding sources: the `inspections` \
table (via run_sql/plot_chart) for facts about specific restaurants, and \
retrieve_regulation for Utah's R392-100 Food Service Sanitation Rule and \
SLC county's inspection-process page. Use run_sql/plot_chart for any \
number, ranking, or visual about restaurants. Use retrieve_regulation \
when the user asks why something matters, what a rule requires, or how \
scoring/risk levels work, and cite what it returns in your answer. Never \
state a number or a regulatory claim you haven't gotten from a tool."""


def build_agent(con, chart_sink: list, retriever, model: str | None = None, provider: str | None = None, verbose: bool = False):
    llm = get_llm(model, provider)
    tools = make_tools(con, chart_sink) + [make_rag_tool(retriever)]
    return create_agent(llm, tools, system_prompt=SYSTEM_PROMPT, debug=verbose)
