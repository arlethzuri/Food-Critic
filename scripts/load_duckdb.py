"""Load the normalized food-health tables into DuckDB (db/schema.dbml).

Sources: data/final/*.csv (built by data/processed/clean_processed.ipynb),
plus data/processed/category-Utah_food.csv and review-Utah_food*.csv, which
pass through untouched so aren't duplicated into final/.

Output: db/food_health.duckdb (overwritten on each run)

  conda run -n food-health-viz python scripts/load_duckdb.py
"""
from __future__ import annotations

from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
FINAL = ROOT / "data" / "final"
PROCESSED = ROOT / "data" / "processed"
DB_PATH = ROOT / "db" / "food_health.duckdb"

CSV = {
    "establishment_keys": FINAL / "establishment_keys.csv",
    "category": PROCESSED / "category-Utah_food.csv",
    "establishments": FINAL / "establishments.csv",
    "establishment_attributes": FINAL / "establishment_attributes.csv",
    "establishment_categories": FINAL / "establishment_categories.csv",
    "gmap_hours": FINAL / "gmap_hours.csv",
    "review": PROCESSED / "review-Utah_food.csv",
    "inspection_types": FINAL / "inspection_types.csv",
    "inspections": FINAL / "inspections.csv",
    "violation_codes": FINAL / "violation_codes.csv",
    "violations": FINAL / "violations.csv",
}

# Load order matters: parents before the tables that FK-reference them.
TABLES = (
    "establishment_keys",
    "category",
    "establishments",
    "establishment_attributes",
    "establishment_categories",
    "gmap_hours",
    "review",
    "inspection_types",
    "inspections",
    "violation_codes",
    "violations",
)

DDL = """
CREATE TABLE establishment_keys (
    slchd_establishment_key VARCHAR PRIMARY KEY,
    name VARCHAR NOT NULL,
    address VARCHAR NOT NULL,
    city VARCHAR NOT NULL,
    city_state_zip VARCHAR,
    establishment_type VARCHAR,
    source VARCHAR,
    slchd_lat DOUBLE,
    slchd_lon DOUBLE,
    geocode_status VARCHAR
);

CREATE TABLE category (
    category_id INTEGER PRIMARY KEY,
    category VARCHAR
);

CREATE TABLE establishments (
    gmap_id VARCHAR PRIMARY KEY,
    name VARCHAR,
    address VARCHAR,
    description VARCHAR,
    geom GEOMETRY,
    avg_rating DOUBLE,
    num_of_reviews INTEGER,
    price VARCHAR,
    slchd_establishment_key VARCHAR REFERENCES establishment_keys(slchd_establishment_key)
);

CREATE TABLE establishment_attributes (
    gmap_id VARCHAR NOT NULL REFERENCES establishments(gmap_id),
    attribute VARCHAR NOT NULL,
    PRIMARY KEY (gmap_id, attribute)
);

CREATE TABLE establishment_categories (
    gmap_id VARCHAR NOT NULL REFERENCES establishments(gmap_id),
    category_id INTEGER NOT NULL REFERENCES category(category_id),
    PRIMARY KEY (gmap_id, category_id)
);

CREATE TABLE gmap_hours (
    gmap_id VARCHAR NOT NULL REFERENCES establishments(gmap_id),
    day INTEGER NOT NULL,
    open_min BIGINT,
    open_max BIGINT,
    PRIMARY KEY (gmap_id, day)
);

CREATE TABLE review (
    user_id VARCHAR,
    name VARCHAR,
    "time" BIGINT,
    rating DOUBLE,
    text VARCHAR,
    resp VARCHAR,
    gmap_id VARCHAR REFERENCES establishments(gmap_id)
);

CREATE TABLE inspection_types (
    inspection_type_id INTEGER PRIMARY KEY,
    description VARCHAR
);

CREATE TABLE inspections (
    inspection_id BIGINT PRIMARY KEY,
    slchd_establishment_key VARCHAR NOT NULL REFERENCES establishment_keys(slchd_establishment_key),
    inspection_date DATE NOT NULL,
    inspection_type_id INTEGER REFERENCES inspection_types(inspection_type_id),
    inspection_score INTEGER
);

CREATE TABLE violation_codes (
    violation_code_id INTEGER PRIMARY KEY,
    code_text VARCHAR NOT NULL,
    asterisk_count INTEGER NOT NULL,
    critical BOOLEAN NOT NULL
);

CREATE TABLE violations (
    violation_id BIGINT PRIMARY KEY,
    inspection_id BIGINT NOT NULL REFERENCES inspections(inspection_id),
    violation_code_id INTEGER NOT NULL REFERENCES violation_codes(violation_code_id),
    violation_description VARCHAR,
    violation_occurrences INTEGER,
    violation_cos BOOLEAN,
    violation_phr VARCHAR
);
"""


def load(db_path: Path = DB_PATH, csv: dict[str, Path] = CSV) -> dict[str, int]:
    """Load every CSV in `csv` into its matching table. Returns {table: row_count}."""
    missing = [name for name, p in csv.items() if not p.exists()]
    if missing:
        raise FileNotFoundError(f"missing source CSVs: {missing}")

    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    con = duckdb.connect(str(db_path))
    try:
        con.execute("INSTALL spatial; LOAD spatial;")
        con.execute(DDL)

        con.execute(
            """
            INSERT INTO establishment_keys
            SELECT
                slchd_establishment_key, name, address, city, city_state_zip,
                establishment_type, source, slchd_lat, slchd_lon, geocode_status
            FROM read_csv_auto(?, header=true, sample_size=-1)
            """,
            [str(csv["establishment_keys"])],
        )

        con.execute(
            "INSERT INTO category SELECT category_id, category "
            "FROM read_csv_auto(?, header=true, sample_size=-1)",
            [str(csv["category"])],
        )

        # CSV has no geometry type — build it here from raw lat/lon.
        con.execute(
            """
            INSERT INTO establishments
            SELECT
                gmap_id, name, address, description,
                ST_Point(longitude, latitude) AS geom,
                avg_rating, num_of_reviews, price,
                NULLIF(slchd_establishment_key, '') AS slchd_establishment_key
            FROM read_csv_auto(?, header=true, sample_size=-1)
            """,
            [str(csv["establishments"])],
        )

        con.execute(
            "INSERT INTO establishment_attributes SELECT gmap_id, attribute "
            "FROM read_csv_auto(?, header=true, sample_size=-1)",
            [str(csv["establishment_attributes"])],
        )

        con.execute(
            "INSERT INTO establishment_categories SELECT gmap_id, category_id "
            "FROM read_csv_auto(?, header=true, sample_size=-1)",
            [str(csv["establishment_categories"])],
        )

        con.execute(
            "INSERT INTO gmap_hours SELECT gmap_id, day, open_min, open_max "
            "FROM read_csv_auto(?, header=true, sample_size=-1)",
            [str(csv["gmap_hours"])],
        )

        con.execute(
            """
            INSERT INTO review
            SELECT user_id, name, "time", rating, text, resp, gmap_id
            FROM read_csv_auto(?, header=true, sample_size=-1)
            """,
            [str(csv["review"])],
        )

        con.execute(
            "INSERT INTO inspection_types SELECT inspection_type_id, description "
            "FROM read_csv_auto(?, header=true, sample_size=-1)",
            [str(csv["inspection_types"])],
        )

        con.execute(
            """
            INSERT INTO inspections
            SELECT
                inspection_id,
                slchd_establishment_key,
                inspection_date,
                inspection_type_id,
                TRY_CAST(TRY_CAST(inspection_score AS DOUBLE) AS INTEGER) AS inspection_score
            FROM read_csv_auto(?, header=true, sample_size=-1)
            """,
            [str(csv["inspections"])],
        )

        con.execute(
            "INSERT INTO violation_codes SELECT violation_code_id, code_text, asterisk_count, critical "
            "FROM read_csv_auto(?, header=true, sample_size=-1)",
            [str(csv["violation_codes"])],
        )

        con.execute(
            """
            INSERT INTO violations
            SELECT
                violation_id, inspection_id, violation_code_id, violation_description,
                TRY_CAST(TRY_CAST(violation_occurrences AS DOUBLE) AS INTEGER) AS violation_occurrences,
                TRY_CAST(violation_cos AS BOOLEAN) AS violation_cos,
                violation_phr
            FROM read_csv_auto(?, header=true, sample_size=-1)
            """,
            [str(csv["violations"])],
        )

        return {t: con.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}
    finally:
        con.close()


def main() -> None:
    counts = load()
    print(f"wrote {DB_PATH}")
    for table in TABLES:
        print(f"  {table}: {counts[table]:,}")


if __name__ == "__main__":
    main()
