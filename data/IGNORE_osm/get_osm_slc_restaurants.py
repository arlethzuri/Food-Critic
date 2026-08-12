#!/usr/bin/env python3
"""
OpenStreetMap restaurant collector for Salt Lake City (Overpass API).

Pulls every mapped dining POI inside the Salt Lake City, UT administrative
boundary — amenities like restaurant/cafe/fast_food plus a few food shops
that show up on OSM as eateries. Complements the SLCHD inspection scrape
with geometry, cuisine, hours, and contact tags that the health portal
does not publish.

Public Overpass endpoint (no API key). Be polite: one query covers the
whole city; retries back off on 429/504. Re-runs overwrite the CSV (OSM
is a snapshot, not an incremental scrape).

Dependencies:
  requests (see requirements.txt)

Examples:
  python osm_slc_restaurants.py
  python osm_slc_restaurants.py --out slc --timeout 180
  python osm_slc_restaurants.py --endpoint https://overpass.kumi.systems/api/interpreter
  python osm_slc_restaurants.py --dry-run   # print query only
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT = SCRIPT_DIR

# Public instances flap under load (504). Rotate on soft failures unless
# the user pins --endpoint.
OVERPASS_ENDPOINTS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
# OSM relation 198770 = Salt Lake City, UT admin boundary (admin_level=8).
# Overpass area id for a relation is 3_600_000_000 + relation_id.
SLC_AREA_ID = 3_600_000_000 + 198_770

# Public Overpass instances reject anonymous/default requests with HTTP 406,
# so identify this client with a descriptive User-Agent.
# https://operations.osmfoundation.org/policies/api/
HEADERS = {
    "User-Agent": "food_critic",
    "Accept": "application/json",
}

# Dining-focused tags. Broad enough for "restaurant data" without dragging
# in every grocery/butcher; use --include-shops for bakery/coffee shops.
AMENITY_VALUES = (
    "restaurant",
    "cafe",
    "fast_food",
    "food_court",
    "ice_cream",
    "bar",
    "pub",
    "biergarten",
    "bistro",
)
SHOP_VALUES = (
    "bakery",
    "pastry",
    "confectionery",
    "coffee",
    "tea",
    "deli",
)

# Flattened columns for the common join keys; everything else stays in tags_json.
CSV_FIELDS = [
    "osm_type",
    "osm_id",
    "name",
    "amenity",
    "shop",
    "cuisine",
    "brand",
    "operator",
    "addr_housenumber",
    "addr_street",
    "addr_unit",
    "addr_city",
    "addr_state",
    "addr_postcode",
    "addr_full",
    "phone",
    "website",
    "email",
    "opening_hours",
    "takeaway",
    "delivery",
    "outdoor_seating",
    "wheelchair",
    "lat",
    "lon",
    "wikidata",
    "wikipedia",
    "osm_url",
    "tags_json",
    "collected_at",
]


def build_query(
    timeout: int,
    include_shops: bool,
    amenity_values: Iterable[str] = AMENITY_VALUES,
    shop_values: Iterable[str] = SHOP_VALUES,
) -> str:
    """Overpass against the SLC admin area, then nodes/ways/relations for food tags.

    Uses the fixed relation→area id (not a name lookup) so the server skips
    the expensive nested area resolve that often 504s on busy mirrors.
    Regex unions keep the statement count low. `out center` gives one lat/lon
    for ways/relations (building footprints).
    """
    amenity_re = "|".join(amenity_values)
    clauses = [f'  nwr["amenity"~"^({amenity_re})$"](area.searchArea);']
    if include_shops:
        shop_re = "|".join(shop_values)
        clauses.append(f'  nwr["shop"~"^({shop_re})$"](area.searchArea);')
    body = "\n".join(clauses)

    return f"""
[out:json][timeout:{timeout}];
area({SLC_AREA_ID})->.searchArea;
(
{body}
);
out center tags;
""".strip()


def _tag(tags: Dict[str, str], *keys: str) -> str:
    for k in keys:
        if tags.get(k):
            return tags[k]
    return ""


def _compose_address(tags: Dict[str, str]) -> str:
    if tags.get("addr:full"):
        return tags["addr:full"]
    parts = [
        " ".join(
            p
            for p in (tags.get("addr:housenumber", ""), tags.get("addr:street", ""))
            if p
        ).strip(),
        tags.get("addr:unit", ""),
        tags.get("addr:city", ""),
        " ".join(
            p for p in (tags.get("addr:state", ""), tags.get("addr:postcode", "")) if p
        ).strip(),
    ]
    return ", ".join(p for p in parts if p)


def element_to_row(el: Dict[str, Any], collected_at: str) -> Optional[Dict[str, str]]:
    """Map one Overpass element to a CSV row. Drops unnamed nodes with no contact."""
    tags = el.get("tags") or {}
    osm_type = el.get("type", "")
    osm_id = el.get("id")
    if osm_id is None:
        return None

    # Ways/relations get center from `out center`; nodes use their own coords.
    if osm_type == "node":
        lat, lon = el.get("lat"), el.get("lon")
    else:
        center = el.get("center") or {}
        lat, lon = center.get("lat"), center.get("lon")

    name = tags.get("name", "")
    # Keep unnamed POIs that still have an amenity/shop — chain outlets
    # sometimes lack a name tag but are still useful for coverage checks.
    amenity = tags.get("amenity", "")
    shop = tags.get("shop", "")
    if not name and not amenity and not shop:
        return None

    return {
        "osm_type": osm_type,
        "osm_id": str(osm_id),
        "name": name,
        "amenity": amenity,
        "shop": shop,
        "cuisine": tags.get("cuisine", ""),
        "brand": tags.get("brand", ""),
        "operator": tags.get("operator", ""),
        "addr_housenumber": tags.get("addr:housenumber", ""),
        "addr_street": tags.get("addr:street", ""),
        "addr_unit": tags.get("addr:unit", ""),
        "addr_city": tags.get("addr:city", ""),
        "addr_state": tags.get("addr:state", ""),
        "addr_postcode": tags.get("addr:postcode", ""),
        "addr_full": _compose_address(tags),
        "phone": _tag(tags, "phone", "contact:phone"),
        "website": _tag(tags, "website", "contact:website", "url"),
        "email": _tag(tags, "email", "contact:email"),
        "opening_hours": tags.get("opening_hours", ""),
        "takeaway": tags.get("takeaway", ""),
        "delivery": tags.get("delivery", ""),
        "outdoor_seating": tags.get("outdoor_seating", ""),
        "wheelchair": tags.get("wheelchair", ""),
        "lat": "" if lat is None else f"{lat:.7f}",
        "lon": "" if lon is None else f"{lon:.7f}",
        "wikidata": tags.get("wikidata", ""),
        "wikipedia": tags.get("wikipedia", ""),
        "osm_url": f"https://www.openstreetmap.org/{osm_type}/{osm_id}",
        "tags_json": json.dumps(tags, ensure_ascii=False, sort_keys=True),
        "collected_at": collected_at,
    }


def fetch_overpass(
    query: str,
    endpoints: List[str],
    retries: int,
    http_timeout: int,
) -> Dict[str, Any]:
    """POST the query, rotating mirrors on 429/5xx so one overloaded host
    doesn't burn the whole retry budget."""
    session = requests.Session()
    session.headers.update(HEADERS)
    last_err: Optional[Exception] = None
    soft = {429, 502, 503, 504}

    for attempt in range(1, retries + 1):
        endpoint = endpoints[(attempt - 1) % len(endpoints)]
        try:
            logging.info("POST %s (attempt %s/%s)", endpoint, attempt, retries)
            resp = session.post(
                endpoint,
                data={"data": query},
                # Client timeout above Overpass [timeout:N] so the server can
                # finish (or return 504) before we abort locally.
                timeout=http_timeout,
            )
            if resp.status_code in soft:
                wait = min(60, 2 ** attempt * 3)
                logging.warning(
                    "Overpass %s from %s; sleeping %ss, next mirror…",
                    resp.status_code,
                    endpoint,
                    wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            payload = resp.json()
            if "elements" not in payload:
                raise RuntimeError(f"Unexpected Overpass payload keys: {list(payload)}")
            logging.info("OK from %s (%d elements)", endpoint, len(payload["elements"]))
            return payload
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_err = exc
            wait = min(60, 2 ** attempt * 3)
            logging.warning("Request failed (%s): %s; sleeping %ss", endpoint, exc, wait)
            time.sleep(wait)
    raise RuntimeError(f"Overpass query failed after {retries} attempts: {last_err}")


def write_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_raw(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def summarize(rows: List[Dict[str, str]]) -> Tuple[int, Dict[str, int]]:
    by_amenity: Dict[str, int] = {}
    for r in rows:
        key = r["amenity"] or f"shop:{r['shop']}" or "(untagged)"
        by_amenity[key] = by_amenity.get(key, 0) + 1
    return len(rows), dict(sorted(by_amenity.items(), key=lambda kv: (-kv[1], kv[0])))


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--out",
        type=Path,
        default=DEFAULT_OUT,
        help=f"Output directory (default: {DEFAULT_OUT})",
    )
    p.add_argument(
        "--endpoint",
        default=None,
        help="Pin a single Overpass interpreter URL (default: rotate mirrors)",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Overpass [timeout:N] in seconds (default: 120)",
    )
    p.add_argument(
        "--retries",
        type=int,
        default=6,
        help="HTTP retries across mirrors on soft failures (default: 6)",
    )
    p.add_argument(
        "--include-shops",
        action="store_true",
        default=True,
        help="Also pull bakery/pastry/coffee/tea/deli shop=* POIs (default: on)",
    )
    p.add_argument(
        "--amenities-only",
        action="store_false",
        dest="include_shops",
        help="Skip shop=* bakery/coffee/etc.; amenity dining tags only",
    )
    p.add_argument(
        "--save-raw",
        action="store_true",
        default=True,
        help="Write overpass_raw.json alongside the CSV (default: on)",
    )
    p.add_argument(
        "--no-save-raw",
        action="store_false",
        dest="save_raw",
        help="Skip writing the raw Overpass JSON",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the Overpass query and exit",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    query = build_query(timeout=args.timeout, include_shops=args.include_shops)
    if args.dry_run:
        print(query)
        return 0

    endpoints = [args.endpoint] if args.endpoint else list(OVERPASS_ENDPOINTS)
    logging.info(
        "Querying Salt Lake City dining POIs via Overpass (%d mirror(s))…",
        len(endpoints),
    )
    payload = fetch_overpass(
        query=query,
        endpoints=endpoints,
        retries=args.retries,
        http_timeout=args.timeout + 60,
    )

    collected_at = datetime.now(timezone.utc).isoformat()
    rows: List[Dict[str, str]] = []
    for el in payload.get("elements", []):
        row = element_to_row(el, collected_at)
        if row:
            rows.append(row)

    # Stable order for diffs across re-runs.
    rows.sort(key=lambda r: (r["osm_type"], int(r["osm_id"])))

    csv_path = args.out / "restaurants.csv"
    write_csv(csv_path, rows)
    if args.save_raw:
        write_raw(args.out / "overpass_raw.json", payload)

    n, by_kind = summarize(rows)
    logging.info("Wrote %s (%d POIs)", csv_path, n)
    for kind, count in by_kind.items():
        logging.info("  %s: %d", kind, count)
    remark = (payload.get("remark") or "").strip()
    if remark:
        logging.warning("Overpass remark: %s", remark)
    return 0


if __name__ == "__main__":
    sys.exit(main())
