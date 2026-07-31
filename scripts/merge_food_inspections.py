"""Merge the two SLC food-inspection datasets in this repo into one flat,
violation-level CSV:

  - data/processed/slc/{establishments,inspections,violations}.csv
    (relational export, joined here on establishment_key / inspection_date)
  - food_inspections.csv
    (raw scrapper.py output: establishment-info rows + inspection-summary
    rows only, no per-violation detail)

Output: data/processed/merged_food_inspections.csv, one row per violation.
Inspections with zero violations, and establishments with zero inspections,
still get one row each with the missing fields left empty, so no
establishment/inspection is dropped for lacking detail.
"""
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRIEND_DIR = ROOT / "data" / "processed" / "slc"
OWN_FILE = ROOT / "food_inspections.csv"
OUT_FILE = ROOT / "data" / "processed" / "merged_food_inspections.csv"

FIELDNAMES = [
    "establishment_name",
    "establishment_type",
    "address",
    "city_state_zip",
    "contact_info",
    "rank",
    "inspection_date",
    "inspection_type",
    "inspection_score",
    "count_critical_violations",
    "count_noncritical_violations",
    "violation_code",
    "violation_description",
    "violation_critical",
    "violation_occurrences",
    "violation_cos",
    "violation_phr",
    "source",
    "scraped_at",
]


def blank_row():
    return {k: "" for k in FIELDNAMES}


def load_friend_data():
    rows = []

    with open(FRIEND_DIR / "establishments.csv", encoding="utf-8") as f:
        establishments = {r["establishment_key"]: r for r in csv.DictReader(f)}

    violations_by_insp = {}
    with open(FRIEND_DIR / "violations.csv", encoding="utf-8") as f:
        for v in csv.DictReader(f):
            key = (v["establishment_key"], v["inspection_date"])
            violations_by_insp.setdefault(key, []).append(v)

    with open(FRIEND_DIR / "inspections.csv", encoding="utf-8") as f:
        inspections = list(csv.DictReader(f))

    # A handful of establishments have two inspections logged on the same
    # date; violations.csv only keys on (establishment, date), not a unique
    # inspection id, so in those cases we attach the full violation list to
    # each same-day inspection rather than guessing which one they belong
    # to or silently dropping them from one.
    inspection_keys = {(i["establishment_key"], i["inspection_date"]) for i in inspections}

    for insp in inspections:
        est = establishments.get(insp["establishment_key"], {})
        key = (insp["establishment_key"], insp["inspection_date"])
        viols = violations_by_insp.get(key, [])

        base = blank_row()
        base.update({
            "establishment_name": est.get("name") or insp.get("name", ""),
            "establishment_type": est.get("establishment_type", ""),
            "address": est.get("address", ""),
            "city_state_zip": est.get("city_state_zip", ""),
            "contact_info": est.get("phone", ""),
            "rank": est.get("rank", ""),
            "inspection_date": insp.get("inspection_date", ""),
            "inspection_type": insp.get("inspection_type", ""),
            "inspection_score": insp.get("score", ""),
            "count_critical_violations": insp.get("critical_violations", ""),
            "count_noncritical_violations": insp.get("noncritical_violations", ""),
            "source": "friend_slc",
            "scraped_at": insp.get("scraped_at") or est.get("scraped_at", ""),
        })

        if viols:
            for v in viols:
                row = dict(base)
                row.update({
                    "violation_code": v.get("code", ""),
                    "violation_description": v.get("observed_violation", ""),
                    "violation_critical": v.get("critical", ""),
                    "violation_occurrences": v.get("occurrences", ""),
                    "violation_cos": v.get("cos", ""),
                    "violation_phr": v.get("phr", ""),
                })
                rows.append(row)
        else:
            rows.append(base)

    # Violations recorded for an (establishment, date) that has no matching
    # row in inspections.csv at all - keep them rather than dropping silently.
    for key, viols in violations_by_insp.items():
        if key in inspection_keys:
            continue
        est_key, date = key
        est = establishments.get(est_key, {})
        for v in viols:
            row = blank_row()
            row.update({
                "establishment_name": est.get("name") or v.get("name", ""),
                "establishment_type": est.get("establishment_type", ""),
                "address": est.get("address", ""),
                "city_state_zip": est.get("city_state_zip", ""),
                "contact_info": est.get("phone", ""),
                "rank": est.get("rank", ""),
                "inspection_date": date,
                "violation_code": v.get("code", ""),
                "violation_description": v.get("observed_violation", ""),
                "violation_critical": v.get("critical", ""),
                "violation_occurrences": v.get("occurrences", ""),
                "violation_cos": v.get("cos", ""),
                "violation_phr": v.get("phr", ""),
                "source": "friend_slc",
                "scraped_at": v.get("scraped_at", ""),
            })
            rows.append(row)

    # Establishments with no inspections at all still get one row.
    inspected_keys = {i["establishment_key"] for i in inspections}
    for key, est in establishments.items():
        if key in inspected_keys:
            continue
        row = blank_row()
        row.update({
            "establishment_name": est.get("name", ""),
            "establishment_type": est.get("establishment_type", ""),
            "address": est.get("address", ""),
            "city_state_zip": est.get("city_state_zip", ""),
            "contact_info": est.get("phone", ""),
            "rank": est.get("rank", ""),
            "source": "friend_slc",
            "scraped_at": est.get("scraped_at", ""),
        })
        rows.append(row)

    return rows


def parse_pipe_fields(text):
    fields = {}
    for part in text.split(" | "):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        fields[k.strip()] = v.strip()
    return fields


def load_own_data():
    """food_inspections.csv alternates, per establishment: one 'Name: ... |
    Address: ... | ...' row, then zero or more 'Date: ... | ...' inspection
    rows. It never captured individual violation codes/descriptions, so
    those columns are left empty for every row from this source."""
    rows = []
    est_base = None
    est_inspections = []

    def flush():
        if est_base is None:
            return
        if est_inspections:
            for insp in est_inspections:
                row = dict(est_base)
                row.update(insp)
                rows.append(row)
        else:
            rows.append(dict(est_base))

    with open(OWN_FILE, encoding="utf-8") as f:
        for rec in csv.DictReader(f):
            data = rec["Inspection Data"]
            fields = parse_pipe_fields(data)

            if data.startswith("Name:"):
                flush()
                est_base = blank_row()
                est_base.update({
                    "establishment_name": fields.get("Name", rec["Establishment"]),
                    "establishment_type": rec["Establishment Type"],
                    "address": fields.get("Address", ""),
                    "city_state_zip": fields.get("City/State/ZIP", ""),
                    "contact_info": fields.get("Phone", ""),
                    "rank": fields.get("Rank", ""),
                    "source": "own_scrape",
                })
                est_inspections = []
            elif data.startswith("Date:"):
                est_inspections.append({
                    "inspection_date": fields.get("Date", ""),
                    "inspection_type": fields.get("Inspection Type", ""),
                    "inspection_score": fields.get("Score", ""),
                    "count_critical_violations": fields.get("Critical Violations", ""),
                    "count_noncritical_violations": fields.get("Non-Critical Violations", ""),
                })
            else:
                # Unexpected shape (e.g. the free-text fallback the scraper
                # writes when it can't find either structure) - keep it
                # rather than dropping it.
                flush()
                est_base = blank_row()
                est_base.update({
                    "establishment_name": rec["Establishment"],
                    "establishment_type": rec["Establishment Type"],
                    "source": "own_scrape",
                })
                est_inspections = [{"violation_description": data}]

        flush()

    return rows


def main():
    rows = load_friend_data() + load_own_data()

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    by_source = {}
    for r in rows:
        by_source[r["source"]] = by_source.get(r["source"], 0) + 1
    print(f"Wrote {len(rows)} rows to {OUT_FILE}")
    for source, count in sorted(by_source.items()):
        print(f"  {source}: {count}")


if __name__ == "__main__":
    main()
