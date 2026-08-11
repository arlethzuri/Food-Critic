"""Build a primary-key lookup table for establishments in the merged inspections CSV.

Key formula matches scripts/load_duckdb.py / db/schema.dbml:
  upper(trim(name) | trim(address) | trim(city))
where city is the left side of city_state_zip before the first comma.

Output: data/processed/establishment_keys.csv
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
MERGED_CSV = ROOT / "data" / "processed" / "merged_food_inspections.csv"
OUT_CSV = ROOT / "data" / "processed" / "establishment_keys.csv"

OUT_COLS = [
    "establishment_key",
    "name",
    "address",
    "city",
    "city_state_zip",
    "establishment_type",
    "source",
]


def generate(csv_path: Path = MERGED_CSV, out_path: Path = OUT_CSV) -> int:
    """Deduplicate establishments by composite key; write one row per key. Returns row count."""
    if not csv_path.exists():
        raise FileNotFoundError(csv_path)

    df = pd.read_csv(csv_path, dtype=str).fillna("")

    # Same derivation as load_duckdb: portal has no stable permit ID, so
    # NAME|ADDRESS|CITY is the natural key used across tables.
    name = df["establishment_name"].str.strip()
    address = df["address"].str.strip()
    # city_state_zip is "CITY, ST ZIP" — take left of first comma, matching split_part(..., 1)
    city = df["city_state_zip"].str.split(",", n=1).str[0].str.strip()

    out = pd.DataFrame(
        {
            "establishment_key": (name + "|" + address + "|" + city).str.upper(),
            "name": name,
            "address": address,
            "city": city,
            "city_state_zip": df["city_state_zip"],
            "establishment_type": df["establishment_type"],
            "source": df["source"],
        }
    )
    out = out[out["establishment_key"].ne("")]
    # First row per key keeps a stable representative for type/source/city_state_zip
    out = out.drop_duplicates(subset=["establishment_key"], keep="first")
    out = out.sort_values("establishment_key").reset_index(drop=True)

    out[OUT_COLS].to_csv(out_path, index=False)
    return len(out)


def main() -> None:
    n = generate()
    print(f"source={MERGED_CSV}")
    print(f"wrote {OUT_CSV}  ({n:,} establishments)")


if __name__ == "__main__":
    main()
