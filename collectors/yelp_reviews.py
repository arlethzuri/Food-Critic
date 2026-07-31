#!/usr/bin/env python3
"""
Yelp Fusion API collector — matches restaurants from the merged inspection
data to Yelp businesses and pulls rating/review-count/price plus a handful
of review excerpts for each.

Source 2 in the Food Critic data plan: subjective/review signal to pair
against the objective SLC inspection records already in
data/processed/merged_food_inspections.csv.

Auth: reads YELP_API_KEY from the environment, or from a .env file at the
repo root (KEY=VALUE per line, no quoting needed). Get a key at
https://www.yelp.com/developers/v3/manage_app (free, no credit card).

Yelp Fusion free tier is capped at 500 calls/day (shared across all
endpoints, resets ~daily). This script uses 1 call per restaurant to match
+ get rating/review_count/price/categories (GET /businesses/search), and
optionally 1 more call per restaurant for up to 3 review excerpts
(GET /businesses/{id}/reviews). It is resume-safe: re-run the same command
on subsequent days and it picks up where it left off.

Estimated runtime for ~1,276 dining-relevant establishments (default
--dining-only filter, see EXCLUDE_TYPE_KEYWORDS below):
  - ratings only (--no-reviews): ~3 runs of 500 calls (~3 days at the free cap)
  - ratings + review excerpts (default): ~6 runs of 500 calls (~6 days)

Dependencies:
  pip install requests

Examples:
  python collectors/yelp_reviews.py
  python collectors/yelp_reviews.py --no-reviews --max-calls 500
  python collectors/yelp_reviews.py --all-types
"""

from __future__ import annotations

import argparse
import csv
import logging
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import requests

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INPUT = ROOT / "data" / "processed" / "merged_food_inspections.csv"
DEFAULT_OUT_DIR = ROOT / "data" / "processed" / "yelp"

SEARCH_URL = "https://api.yelp.com/v3/businesses/search"
REVIEWS_URL = "https://api.yelp.com/v3/businesses/{id}/reviews"

# establishment_type substrings to skip by default — these show up in the
# SLC inspection data but aren't dining venues Yelp would have (pools,
# cosmetology, tattoo, etc). Use --all-types to disable this filter.
EXCLUDE_TYPE_KEYWORDS = [
    "cosmetology", "cosmetics", "piercing", "tattoo", "massage", "recycler",
    "liquid waste", "care facilities", "group homes", "child care",
    "condo/apartment", "schools", "nails", "esthetician",
]

BUSINESS_FIELDS = [
    "establishment_key", "establishment_name", "establishment_address",
    "query_location", "yelp_business_id", "yelp_name", "yelp_address",
    "yelp_rating", "yelp_review_count", "yelp_price", "yelp_categories",
    "yelp_phone", "yelp_url", "match_status", "fetched_at",
]
REVIEW_FIELDS = [
    "establishment_key", "yelp_business_id", "review_id", "review_text",
    "review_rating", "review_time_created", "fetched_at",
]


@dataclass
class Establishment:
    name: str
    address: str
    city_state_zip: str

    @property
    def key(self) -> str:
        return f"{self.name}|{self.address}".strip().upper()

    @property
    def location(self) -> str:
        return f"{self.address}, {self.city_state_zip}".strip(", ")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def load_establishments(input_csv: Path, dining_only: bool) -> List[Establishment]:
    seen: Dict[str, Establishment] = {}
    with open(input_csv, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            name = row["establishment_name"].strip()
            address = row["address"].strip()
            if not name or not address:
                continue
            etype = row.get("establishment_type", "").lower()
            if dining_only and any(kw in etype for kw in EXCLUDE_TYPE_KEYWORDS):
                continue
            est = Establishment(name, address, row.get("city_state_zip", "").strip())
            seen.setdefault(est.key, est)
    return sorted(seen.values(), key=lambda e: e.key)


def load_done_keys(businesses_csv: Path) -> set:
    if not businesses_csv.exists():
        return set()
    with open(businesses_csv, encoding="utf-8") as f:
        return {row["establishment_key"] for row in csv.DictReader(f)}


def open_writer(path: Path, fieldnames: List[str]):
    is_new = not path.exists()
    f = open(path, "a", newline="", encoding="utf-8")
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    if is_new:
        writer.writeheader()
        f.flush()
    return f, writer


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def search_business(session: requests.Session, est: Establishment, log: logging.Logger) -> dict:
    resp = session.get(
        SEARCH_URL,
        params={"term": est.name, "location": est.location, "limit": 1},
        timeout=15,
    )
    if resp.status_code == 429:
        raise RuntimeError("rate_limited")
    resp.raise_for_status()
    businesses = resp.json().get("businesses", [])
    if not businesses:
        return {
            "establishment_key": est.key,
            "establishment_name": est.name,
            "establishment_address": est.address,
            "query_location": est.location,
            "yelp_business_id": "", "yelp_name": "", "yelp_address": "",
            "yelp_rating": "", "yelp_review_count": "", "yelp_price": "",
            "yelp_categories": "", "yelp_phone": "", "yelp_url": "",
            "match_status": "no_match", "fetched_at": now_iso(),
        }
    b = businesses[0]
    return {
        "establishment_key": est.key,
        "establishment_name": est.name,
        "establishment_address": est.address,
        "query_location": est.location,
        "yelp_business_id": b.get("id", ""),
        "yelp_name": b.get("name", ""),
        "yelp_address": ", ".join(b.get("location", {}).get("display_address", [])),
        "yelp_rating": b.get("rating", ""),
        "yelp_review_count": b.get("review_count", ""),
        "yelp_price": b.get("price", ""),
        "yelp_categories": "; ".join(c["title"] for c in b.get("categories", [])),
        "yelp_phone": b.get("display_phone", ""),
        "yelp_url": b.get("url", ""),
        "match_status": "matched",
        "fetched_at": now_iso(),
    }


def fetch_reviews(session: requests.Session, est: Establishment, business_id: str) -> List[dict]:
    resp = session.get(REVIEWS_URL.format(id=business_id), timeout=15)
    if resp.status_code == 429:
        raise RuntimeError("rate_limited")
    resp.raise_for_status()
    out = []
    for r in resp.json().get("reviews", []):
        out.append({
            "establishment_key": est.key,
            "yelp_business_id": business_id,
            "review_id": r.get("id", ""),
            "review_text": r.get("text", ""),
            "review_rating": r.get("rating", ""),
            "review_time_created": r.get("time_created", ""),
            "fetched_at": now_iso(),
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="merged_food_inspections.csv path")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="output directory")
    parser.add_argument("--max-calls", type=int, default=480, help="API call budget for this run (Yelp free tier resets at 500/day; default leaves headroom)")
    parser.add_argument("--delay", type=float, default=0.3, help="seconds to sleep between API calls")
    parser.add_argument("--no-reviews", action="store_true", help="skip the reviews call, only fetch rating/review_count/price/categories")
    parser.add_argument("--all-types", action="store_true", help="don't filter out non-dining establishment types")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("yelp_reviews")

    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("YELP_API_KEY")
    if not api_key:
        log.error("YELP_API_KEY not set. Put it in a .env file at the repo root or export it.")
        return 1

    if not args.input.exists():
        log.error("Input file not found: %s", args.input)
        return 1

    args.out.mkdir(parents=True, exist_ok=True)
    businesses_csv = args.out / "yelp_businesses.csv"
    reviews_csv = args.out / "yelp_reviews.csv"

    establishments = load_establishments(args.input, dining_only=not args.all_types)
    done = load_done_keys(businesses_csv)
    todo = [e for e in establishments if e.key not in done]

    log.info("%d dining-relevant establishments total, %d already done, %d remaining",
              len(establishments), len(done), len(todo))
    if not todo:
        log.info("Nothing to do.")
        return 0

    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {api_key}"})

    b_f, b_writer = open_writer(businesses_csv, BUSINESS_FIELDS)
    r_f, r_writer = open_writer(reviews_csv, REVIEW_FIELDS)

    calls_used = 0
    processed = 0
    try:
        for est in todo:
            if calls_used >= args.max_calls:
                log.info("Hit call budget (%d) for this run.", args.max_calls)
                break
            try:
                result = search_business(session, est, log)
                calls_used += 1
                b_writer.writerow(result)
                b_f.flush()

                if not args.no_reviews and result["match_status"] == "matched" and calls_used < args.max_calls:
                    time.sleep(args.delay)
                    reviews = fetch_reviews(session, est, result["yelp_business_id"])
                    calls_used += 1
                    for rv in reviews:
                        r_writer.writerow(rv)
                    r_f.flush()

                processed += 1
                log.info("[%d/%d] %s -> %s", processed, len(todo), est.name, result["match_status"])

            except RuntimeError as e:
                if str(e) == "rate_limited":
                    log.warning("Hit Yelp's rate limit (daily quota likely exhausted). Stopping — re-run tomorrow.")
                    break
                raise
            except requests.RequestException as e:
                log.warning("Request failed for %s: %s — skipping, will retry next run", est.name, e)
                # Don't count this establishment as done — leave it for the next run.
                continue

            time.sleep(args.delay)
    finally:
        b_f.close()
        r_f.close()

    remaining = len(todo) - processed
    log.info("Done for this run: %d processed, %d API calls used, %d remaining.", processed, calls_used, remaining)
    if remaining > 0:
        log.info("Re-run the same command to continue (resumes automatically).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
