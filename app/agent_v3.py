"""Variant 3: everything Variant 2 has (CSV data + RAG over the food-safety
regulation), plus the ontology-guided hypothesis/evidence pipeline from
semantic/gen_ontology.json — the agent must classify its answer into one
of a fixed set of Hypothesis types (or 'none') and back it with typed
Evidence tagged to ontology concepts, via response_format rather than
free text. This directly targets RQ2 (can the agent explain how it
arrived at a conclusion, in a checkable structure) and is the full
3-condition RQ1 comparison's third leg against variants 1 and 2.
"""
from langchain.agents import create_agent

from llm import get_llm
from ontology import hypothesis_guidance_text, make_classify_tool
from rag_tool import make_rag_tool
from schemas import HypothesisResponse
from tools import make_tools

SYSTEM_PROMPT = """\
You are a food-safety data analyst answering questions about restaurants \
in Salt Lake County. You have three grounding sources: the `inspections` \
table (via run_sql/plot_chart) for facts about specific restaurants, \
retrieve_regulation for Utah's R392-100 Food Service Sanitation Rule and \
SLC county's inspection-process page, and classify_violation to translate \
a raw violation_phr string into the ontology's ViolationType concept. \
Never state a number or a regulatory claim you haven't gotten from a tool.

Your final answer must be structured, not just prose. After gathering \
facts with your tools, decide whether the question calls for a hypothesis \
about an establishment (a recommendation, a warning, or a trend claim) or \
is just a plain data lookup.

{hypothesis_guidance}

For every hypothesis you form (anything other than 'none'), back it with \
supporting_evidence and, where it exists, undermining_evidence — each \
item must cite a specific run_sql result or retrieve_regulation chunk \
(source_ref) and name the ontology concept it bears on \
(relates_to_concept), e.g. 'Violation.critical', 'InspectionTrend.worsening', \
or 'ViolationType.temperature_control' (call classify_violation to get \
this for a violation row). Do not fabricate evidence — every item must \
trace back to an actual tool call you made. If the question is a plain \
lookup (e.g. "what's the address of X"), set hypothesis to 'none' and \
leave both evidence lists empty; still put the answer in narrative_answer.\
"""


def build_agent(con, chart_sink: list, retriever, model: str | None = None, provider: str | None = None, verbose: bool = False):
    llm = get_llm(model, provider)
    tools = make_tools(con, chart_sink) + [make_rag_tool(retriever), make_classify_tool()]
    system_prompt = SYSTEM_PROMPT.format(hypothesis_guidance=hypothesis_guidance_text())
    return create_agent(
        llm,
        tools,
        system_prompt=system_prompt,
        response_format=HypothesisResponse,
        debug=verbose,
    )
