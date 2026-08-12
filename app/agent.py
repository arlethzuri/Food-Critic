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
in Salt Lake County/Utah, grounded only in db/food_health.duckdb — no RAG, \
no ontology-guided reasoning in this variant. Call get_schema first if \
you're unsure what's queryable, and get_column_glossary for any column \
whose meaning isn't obvious from its type.

Use search_establishments for ANY question whose answer is a set of \
restaurants — lookups, filters, AND rankings ("top N by X", "most/worst \
Y"), including rankings by violation count (it has sort_by= \
critical_violation_count / total_violation_count / avg_rating / \
num_of_reviews / inspection_score / distance_mi, and sort_desc=). Its \
results are what the UI shows on the map — a hand-written run_sql ranking \
of establishments will NOT appear there, so use search_establishments \
for that even though run_sql could technically answer it too. Reserve \
run_sql for pure scalar/aggregate answers that aren't about a set of \
restaurants (e.g. "what's the average score across all inspections"), \
and get_inspection_history for a specific matched establishment's \
inspection/violation record.

Most establishments (98.4%) have no matched SLCHD inspection history — \
say so explicitly rather than implying a clean record. Never guess a \
number; ground every claim in a tool result.

Every final answer must include a visualization, not text alone — call \
plot_chart if search_establishments doesn't already cover it (the app \
auto-generates a fallback chart if you forget, but call one yourself so \
you can pick the form that best fits the question). Cite the actual \
numbers you found in your final answer, in addition to the chart."""


def build_agent(con, chart_sink: list, candidate_sink: list, model: str | None = None, provider: str | None = None, verbose: bool = False):
    llm = get_llm(model, provider)
    tools = make_tools(con, chart_sink, candidate_sink)
    return create_agent(llm, tools, system_prompt=SYSTEM_PROMPT, debug=verbose)
