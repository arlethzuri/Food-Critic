#!/usr/bin/env python3
"""
Populates semantic/violation_map.csv, the mapping gen_ontology.json's
ViolationType class calls for ("hand-curated ... keyed on code and/or
phr") but that didn't exist yet. Buckets every distinct violation_phr
value in the merged data into one of the ontology's six ViolationType
values via keyword rules, falling back to "other" for anything that
doesn't fit (the ontology's list of six wasn't meant to be exhaustive of
every raw rubric label in the real data).

This is a first-pass heuristic, not a final hand-curation — the output
CSV is plain text and meant to be corrected by hand where the keyword
rules get something wrong (rows are sorted by frequency descending, so
fixing the top of the file first covers the most inspections).

Usage: python3 semantic/build_violation_map.py
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "processed" / "merged_food_inspections.csv"
OUT_PATH = ROOT / "semantic" / "violation_map.csv"

# Checked in this order; first match wins. Order matters where keywords
# could plausibly belong to more than one bucket (e.g. "Handwashing
# Sink-Installation" contains both a hygiene term and a facility term —
# hygiene_practice is checked first so it wins).
RULES: list[tuple[str, list[str]]] = [
    ("temperature_control", [
        "temperature", "cold holding", "hot holding", "cooling", "reheat",
        "thaw", "time as a public health", "date marking", "cooking",
    ]),
    ("pest_presence", [
        "pest", "insect", "rodent", "bird", "outer openings",
    ]),
    ("documentation", [
        "permit", "haccp", "certification", "registration", "training",
        "records,", "variance requirement", "compliance with food law",
        "agreement", "food labels", "when plans are required",
        "common name of food", "common name**", "allergen",
        "clean air act",
    ]),
    ("hygiene_practice", [
        "hand", "glove", "fingernail", "jewelry prohibition",
        "hair restraint", "outer clothing", "person in charge",
        "demonstration of knowledge", "employee accomodations",
        "eating, drinking, or using tobacco", "vomiting", "diarrheal",
        "personal care items",
    ]),
    ("cross_contamination", [
        "contamination", "cross connection", "separation", "segregation",
        "poisonous or toxic", "food contact with equipment",
        "package integrity",
    ]),
    ("facility_maintenance", [
        "floor", "wall", "ceiling", "lighting", "light bulb", "ventilation",
        "repair", "plumbing", "sewage", "water supply", "toilet", "drain",
        "sink", "warewash", "refuse", "waste", "garbage", "equipment",
        "utensil", "surface", "facilit", "premises", "construction",
        "elevation", "sealing", "carpet", "mat", "duckboard", "junctures",
        "cleaning", "mop", "wiping cloth", "cleanable fixtures",
        "approved system", "sanitizing solution", "backflow", "receptacle",
        "hot water and chemical", "multi-use", "single-service",
        "single-use articles", "kitchenware", "tableware", "food storage",
    ]),
]


def classify(phr: str) -> tuple[str, str]:
    lower = phr.lower()
    for violation_type, keywords in RULES:
        for kw in keywords:
            if kw in lower:
                return violation_type, kw
    return "other", ""


def main() -> None:
    con = duckdb.connect(":memory:")
    con.execute(
        f"CREATE VIEW t AS SELECT * FROM read_csv_auto('{CSV_PATH.as_posix()}', ALL_VARCHAR=TRUE)"
    )
    df = con.execute("""
        SELECT violation_phr, COUNT(*) AS n
        FROM t
        WHERE violation_phr != ''
        GROUP BY 1
        ORDER BY n DESC
    """).fetchdf()

    rows = []
    for phr, n in zip(df["violation_phr"], df["n"]):
        violation_type, matched_keyword = classify(phr)
        rows.append({
            "violation_phr": phr,
            "violation_type": violation_type,
            "matched_keyword": matched_keyword,
            "n_occurrences": int(n),
        })

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["violation_phr", "violation_type", "matched_keyword", "n_occurrences"])
        writer.writeheader()
        writer.writerows(rows)

    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["violation_type"]] = by_type.get(r["violation_type"], 0) + r["n_occurrences"]
    print(f"Wrote {len(rows)} distinct phr labels to {OUT_PATH}")
    print("Occurrences by violation_type:")
    for vt, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {vt}: {n}")


if __name__ == "__main__":
    main()
