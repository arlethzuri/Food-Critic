"""Loads semantic/ontology.json and semantic/violation_map.csv and exposes
what Variant 3 needs from them: the fixed Hypothesis vocabulary and its
evidence-gathering guidance (for the system prompt), and a
classify_violation tool the agent can call to translate a raw
violation_phr string into the ontology's ViolationType concept.
"""
import csv
import json
from pathlib import Path

from langchain_core.tools import tool

ROOT = Path(__file__).resolve().parent.parent
ONTOLOGY_PATH = ROOT / "semantic" / "ontology.json"
VIOLATION_MAP_PATH = ROOT / "semantic" / "violation_map.csv"

with open(ONTOLOGY_PATH, encoding="utf-8") as f:
    _ONTOLOGY = json.load(f)

HYPOTHESIS_TYPES = _ONTOLOGY["classes"]["Hypothesis"]["values"]
HYPOTHESIS_EVIDENCE_MAP = _ONTOLOGY["hypothesis_evidence_map"]
VIOLATION_TYPES = _ONTOLOGY["classes"]["ViolationType"]["values"]
DATA_QUALITY_FLAGS = _ONTOLOGY["data_quality_flags"]


def _load_violation_map() -> dict[str, tuple[str, str]]:
    mapping = {}
    if not VIOLATION_MAP_PATH.exists():
        return mapping
    with open(VIOLATION_MAP_PATH, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            mapping[row["violation_phr"].strip().lower()] = (
                row["violation_type"],
                row["matched_keyword"],
            )
    return mapping


_VIOLATION_MAP = _load_violation_map()


def hypothesis_guidance_text() -> str:
    """Formats hypothesis_evidence_map from the ontology into a compact
    block for the system prompt: the fixed hypothesis vocabulary plus
    what evidence to look for, for each one."""
    lines = [
        "Fixed hypothesis vocabulary (pick one of these, or 'none' if the "
        "question is a plain data lookup that doesn't call for a hypothesis):",
    ]
    for h_type in HYPOTHESIS_TYPES:
        lines.append(f"\n- {h_type}:")
        for item in HYPOTHESIS_EVIDENCE_MAP.get(h_type, []):
            lines.append(f"    - {item}")
    lines.append(
        "\nData quality flags — respect these when forming a hypothesis "
        "or citing evidence (call get_schema for full table/column detail):"
    )
    for note in DATA_QUALITY_FLAGS.values():
        lines.append(f"    - {note}")
    return "\n".join(lines)


_CLASSIFY_VIOLATION_DESC = (
    "Look up the ontology's ViolationType bucket for a raw violation_phr string "
    "(as returned by run_sql from the violations.violation_phr column). Returns "
    f"the ViolationType (one of: {', '.join(VIOLATION_TYPES)}) plus the keyword "
    "that matched. Use this to translate raw query results into ontology "
    "concepts for your evidence's relates_to_concept field."
)


def make_classify_tool():
    @tool(description=_CLASSIFY_VIOLATION_DESC)
    def classify_violation(violation_phr: str) -> str:
        key = violation_phr.strip().lower()
        if key in _VIOLATION_MAP:
            violation_type, matched_keyword = _VIOLATION_MAP[key]
            return f"ViolationType.{violation_type} (matched keyword: '{matched_keyword}')"
        # Fall back to substring match against known phr strings, in case
        # the agent passes a slightly different string than the exact column value.
        for known_phr, (violation_type, matched_keyword) in _VIOLATION_MAP.items():
            if key in known_phr or known_phr in key:
                return f"ViolationType.{violation_type} (fuzzy match on '{known_phr}', keyword: '{matched_keyword}')"
        return "ViolationType.other (no match found in semantic/violation_map.csv)"

    return classify_violation
