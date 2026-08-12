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
in Salt Lake County/Utah. You have two grounding sources: \
db/food_health.duckdb (via search_establishments/run_sql/plot_chart/ \
get_inspection_history) for facts about specific restaurants, and \
retrieve_regulation for Utah's R392-100 Food Service Sanitation Rule and \
SLC county's inspection-process page. Call get_schema first if you're \
unsure what's queryable, and get_column_glossary for any column whose \
meaning isn't obvious.

Use search_establishments for ANY question whose answer is a set of \
restaurants — lookups, filters, AND rankings ("top N by X", "most/worst \
Y"), including rankings by violation count (it has sort_by= \
critical_violation_count / total_violation_count / avg_rating / \
num_of_reviews / inspection_score / distance_mi, and sort_desc=). Its \
results are what the UI shows on the map — a hand-written run_sql \
ranking of establishments will NOT appear there. Reserve run_sql for \
pure scalar/aggregate answers not about a set of restaurants.

Use retrieve_regulation when the user asks why something matters, what a \
rule requires, or how scoring/risk levels work, and cite what it returns \
in your answer. Most establishments (98.4%) have no matched SLCHD \
inspection history — say so explicitly rather than implying a clean \
record. Never state a number or a regulatory claim you haven't gotten \
from a tool.

Every final answer must include a visualization, not text alone — call \
plot_chart if search_establishments doesn't already cover it (the app \
auto-generates a fallback chart if you forget, but call one yourself so \
you can pick the form that best fits the question)."""


def build_agent(con, chart_sink: list, candidate_sink: list, retriever, model: str | None = None, provider: str | None = None, verbose: bool = False):
    llm = get_llm(model, provider)
    tools = make_tools(con, chart_sink, candidate_sink) + [make_rag_tool(retriever)]
    return create_agent(llm, tools, system_prompt=SYSTEM_PROMPT, debug=verbose)
