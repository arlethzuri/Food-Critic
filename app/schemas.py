"""Structured output schema for Variant 3, mirroring the ontology's
Hypothesis and Evidence classes (semantic/ontology.json). Passed as
create_agent's response_format so the agent's final answer is coerced
into this shape instead of free text — this is what dashboard_v3.py
renders as the reasoning/evidence panel.
"""
from typing import Literal

from pydantic import BaseModel, Field

from ontology import HYPOTHESIS_TYPES

# Built from the live ontology rather than hardcoded, so this can't drift
# out of sync with semantic/ontology.json's Hypothesis.values again.
HypothesisType = Literal[tuple(HYPOTHESIS_TYPES) + ("none",)]


class EvidenceItem(BaseModel):
    source_type: Literal["sql_fact", "rag_chunk"] = Field(
        description="Where this evidence came from: a run_sql/search_establishments query result, or a retrieve_regulation chunk."
    )
    source_ref: str = Field(
        description="Specific reference: e.g. a gmap_id, or an establishment name + inspection date + violation code, "
        "or a regulation section/page citation as returned by retrieve_regulation."
    )
    relates_to_concept: str = Field(
        description="Ontology concept this bears on, e.g. 'ViolationCode.critical', 'InspectionTrend.worsening', "
        "'ViolationType.temperature_control' (use classify_violation to get this for violation rows)."
    )
    summary: str = Field(description="One-sentence statement of the fact.")
    direction: Literal["supports", "undermines"]


class CandidatePoolItem(BaseModel):
    """One establishment the agent considered, with the raw metric values
    the UI needs to render it on the map and re-filter it locally as the
    user drags the Strictness slider — no LLM re-query on drag."""

    gmap_id: str
    name: str
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    avg_rating: float | None = None
    num_of_reviews: int | None = None
    price: str | None = None
    distance_mi: float | None = Field(
        default=None, description="Distance from the query location, if the question involved one."
    )
    slchd_establishment_key: str | None = Field(
        default=None, description="Null means no matched SLCHD inspection history — not an error."
    )
    inspection_score: float | None = Field(
        default=None, description="Most recent inspection score, if slchd_establishment_key is set."
    )
    critical_violation_count: int | None = Field(
        default=None, description="Count of critical violations across this establishment's whole inspection history."
    )
    total_violation_count: int | None = Field(
        default=None, description="Count of all violations (critical + non-critical) across this establishment's whole inspection history."
    )
    included: bool = Field(
        default=True, description="Whether this candidate made it into the final answer (vs. considered and excluded)."
    )


class HypothesisResponse(BaseModel):
    narrative_answer: str = Field(
        description="Plain-language answer to the user's question. If a hypothesis was formed, "
        "reference it and its evidence here in prose."
    )
    hypothesis: HypothesisType = Field(
        description="Best-fitting hypothesis type from the fixed ontology vocabulary, "
        "or 'none' if the question is a plain data lookup that doesn't call for one."
    )
    confidence: Literal["low", "medium", "high"] = Field(
        description="Your confidence in the hypothesis, given the evidence gathered. "
        "Use 'low' if evidence is thin or mixed."
    )
    establishment_name: str = Field(
        default="", description="The establishment this hypothesis is about, if any."
    )
    supporting_evidence: list[EvidenceItem] = Field(default_factory=list)
    undermining_evidence: list[EvidenceItem] = Field(default_factory=list)
    # Not filled in by the model — chat_utils.run_structured_agent overwrites
    # this from the actual search_establishments tool-call results after the
    # agent finishes, so it can't drift from what the agent really queried.
    # Left as a real field (not computed purely client-side) so the whole
    # structured answer, including its candidate pool, serializes as one object.
    candidate_pool: list[CandidatePoolItem] = Field(default_factory=list)
