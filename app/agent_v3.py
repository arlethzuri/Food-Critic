"""Variant 3: everything Variant 2 has (normalized DB + RAG over the
food-safety regulation), plus the ontology-guided hypothesis/evidence
pipeline from semantic/ontology.json — the agent must classify its answer
into one of a fixed set of Hypothesis types (or 'none') and back it with
typed Evidence tagged to ontology concepts, via response_format rather
than free text. This directly targets RQ2 (can the agent explain how it
arrived at a conclusion, in a checkable structure) and is the full
3-condition RQ1 comparison's third leg against variants 1 and 2.
"""
from langchain.agents import create_agent

from llm import get_llm
from ontology import hypothesis_guidance_text, make_classify_tool
from rag_tool import make_rag_tool
from schemas import HypothesisResponse
from tools import CHARTING_POLICY, GROUNDING_POLICY, make_tools

SYSTEM_PROMPT = """\
You are a food-safety data analyst answering questions about restaurants \
in Salt Lake County/Utah. You have three grounding sources: \
db/food_health.duckdb (via search_establishments/run_sql/plot_chart/ \
get_inspection_history) for facts about specific restaurants, \
retrieve_regulation for Utah's R392-100 Food Service Sanitation Rule and \
SLC county's inspection-process page, and classify_violation to translate \
a raw violation_phr string into the ontology's ViolationType concept. \
Call get_schema first if you're unsure what's queryable, and \
get_column_glossary for any column whose meaning isn't obvious. Always \
use search_establishments (not hand-written SQL) to find candidate \
restaurants for a hypothesis — including ranking questions ("top N by X", \
"most/worst Y"), via its sort_by= critical_violation_count / \
total_violation_count / avg_rating / num_of_reviews / inspection_score / \
distance_mi and sort_desc= — every establishment it returns becomes part \
of the map/evidence view shown to the user, so a hand-written SQL query \
(even one that technically answers the question) would leave the \
Reasoning tab empty.

{grounding_policy}

Your final answer must be structured, not just prose. {charting_policy} \
search_establishments' results additionally populate the Reasoning tab's \
map step automatically, on top of whatever plot_chart you called. After \
gathering facts with your tools, decide whether the question calls for a \
hypothesis about an establishment (a recommendation, a warning, or a \
trend claim) or is just a plain data lookup.

{hypothesis_guidance}

For every hypothesis you form (anything other than 'none'), back it with \
supporting_evidence and, where it exists, undermining_evidence — each \
item must cite a specific search_establishments/run_sql result or \
retrieve_regulation chunk (source_ref) and name the ontology concept it \
bears on (relates_to_concept), e.g. 'ViolationCode.critical', \
'InspectionTrend.worsening', or 'ViolationType.temperature_control' (call \
classify_violation to get this for a violation row). Do not fabricate \
evidence — every item must trace back to an actual tool call you made. If \
the question is a plain lookup (e.g. "what's the address of X"), set \
hypothesis to 'none' and leave both evidence lists empty; still put the \
answer in narrative_answer. Leave candidate_pool empty — it's filled in \
separately from your actual search_establishments calls, not by you.\
"""


def build_agent(con, chart_sink: list, candidate_sink: list, retriever, model: str | None = None, provider: str | None = None, verbose: bool = False):
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
        debug=verbose,
    )
