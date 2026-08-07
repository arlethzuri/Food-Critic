"""Structured output schema for Variant 3, mirroring the ontology's
Hypothesis and Evidence classes (semantic/gen_ontology.json). Passed as
create_agent's response_format so the agent's final answer is coerced
into this shape instead of free text — this is what dashboard_v3.py
renders as the reasoning/evidence panel.
"""
from typing import Literal

from pydantic import BaseModel, Field

HypothesisType = Literal[
    "safe_bet",
    "health_risk_concern",
    "improving_compliance",
    "declining_compliance",
    "repeat_critical_violator",
    "none",
]


class EvidenceItem(BaseModel):
    source_type: Literal["sql_fact", "rag_chunk"] = Field(
        description="Where this evidence came from: a run_sql query result, or a retrieve_regulation chunk."
    )
    source_ref: str = Field(
        description="Specific reference: e.g. an establishment name + inspection date + violation code, "
        "or a regulation section/page citation as returned by retrieve_regulation."
    )
    relates_to_concept: str = Field(
        description="Ontology concept this bears on, e.g. 'Violation.critical', 'InspectionTrend.worsening', "
        "'ViolationType.temperature_control' (use classify_violation to get this for violation rows)."
    )
    summary: str = Field(description="One-sentence statement of the fact.")
    direction: Literal["supports", "undermines"]


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
