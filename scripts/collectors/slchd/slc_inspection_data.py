#!/usr/bin/env python3
"""
Salt Lake County Health Department inspection scraper.

Source (iframe behind https://www.saltlakecounty.gov/health/inspection/):
  https://public.cdpehs.com/UTEnvPbl/VW_EST_PUBLIC/ShowVW_EST_PUBLICTablePage.aspx

There is no public API. This replays ASP.NET postbacks slowly and writes CSVs.
The portal only exposes whatever history is on each establishment's inspection
table (typically up to ~10 recent inspections) — that is all "historical" data
available publicly.

Estimated runtime (Food Service, ~55 pages / ~5.5k establishments):
  - inspections only (--skip-violations): ~4–6 hours at --delay 1.5
  - with violation details (default): often 15–30+ hours depending on history depth

Resume-safe: re-run the same command; completed establishments are skipped.
Logs go to console and {--out}/scrape.log.

Dependencies:
  pip install requests beautifulsoup4 lxml

Examples:
  python collectors/slc_inspection_data.py
  python collectors/slc_inspection_data.py --delay 2 --skip-violations
  python collectors/slc_inspection_data.py --area All --out data/slc
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import requests
from bs4 import BeautifulSoup

LIST_URL = (
    "https://public.cdpehs.com/UTEnvPbl/VW_EST_PUBLIC/ShowVW_EST_PUBLICTablePage.aspx"
)
USER_AGENT = (
    "Mozilla/5.0 (compatible; food-health-viz/0.1; research; "
    "+https://github.com/local/food-health-viz)"
)

SEARCH_BUTTON = "ctl00$PageContent$VW_EST_PUBLICSearchButton$_Button"
NEXT_PAGE = "ctl00$PageContent$VW_EST_PUBLICPagination$_NextPage"
GOTO_PAGE = "ctl00$PageContent$VW_EST_PUBLICPagination$_PageSizeButton"
CURRENT_PAGE = "ctl00$PageContent$VW_EST_PUBLICPagination$_CurrentPage"
TOTAL_PAGES = "#ctl00_PageContent_VW_EST_PUBLICPagination__TotalPages"
AREA_FILTER = "ctl00$PageContent$CODE_DESCRIPTIONFilter"
CITY_FILTER = "ctl00$PageContent$PREMISE_CITYFilter"
OK_BUTTON = "ctl00$PageContent$OKButton$_Button"

DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
POSTBACK_RE = re.compile(r"__doPostBack\('([^']+)'")


@dataclass
class EstablishmentRow:
    name: str
    address: str
    city: str
    insp_target: str
    list_page: int
    row_index: int

    @property
    def key(self) -> str:
        return f"{self.name}|{self.address}|{self.city}".upper()


class SlcScraper:
    def __init__(
        self,
        out_dir: Path,
        area: str = "Food Service",
        city: str = "",
        delay: float = 1.5,
        jitter: float = 0.5,
        skip_violations: bool = False,
        max_pages: Optional[int] = None,
        max_establishments: Optional[int] = None,
        retries: int = 4,
    ) -> None:
        self.out_dir = out_dir
        self.area = area
        self.city = city
        self.delay = delay
        self.jitter = jitter
        self.skip_violations = skip_violations
        self.max_pages = max_pages
        self.max_establishments = max_establishments
        self.retries = retries

        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self.url = LIST_URL
        self.soup: Optional[BeautifulSoup] = None

        self.est_path = out_dir / "establishments.csv"
        self.insp_path = out_dir / "inspections.csv"
        self.viol_path = out_dir / "violations.csv"
        self.checkpoint_path = out_dir / "checkpoint.json"

        self.done_keys: Set[str] = set()
        self.stats = {
            "establishments": 0,
            "inspections": 0,
            "violations": 0,
            "skipped": 0,
            "errors": 0,
        }

    # --- I/O -----------------------------------------------------------------

    def setup_output(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_csv(
            self.est_path,
            [
                "establishment_key",
                "name",
                "address",
                "city",
                "city_state_zip",
                "phone",
                "establishment_type",
                "rank",
                "list_page",
                "scraped_at",
            ],
        )
        self._ensure_csv(
            self.insp_path,
            [
                "establishment_key",
                "name",
                "inspection_date",
                "inspection_type",
                "score",
                "critical_violations",
                "noncritical_violations",
                "scraped_at",
            ],
        )
        self._ensure_csv(
            self.viol_path,
            [
                "establishment_key",
                "name",
                "inspection_date",
                "code",
                "observed_violation",
                "points",
                "critical",
                "occurrences",
                "cos",
                "phr",
                "scraped_at",
            ],
        )
        self._load_checkpoint()

    def _ensure_csv(self, path: Path, fieldnames: List[str]) -> None:
        if path.exists():
            return
        with path.open("w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=fieldnames).writeheader()

    def _append_rows(self, path: Path, fieldnames: List[str], rows: Iterable[Dict[str, Any]]) -> None:
        rows = list(rows)
        if not rows:
            return
        with path.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            for row in rows:
                writer.writerow(row)

    def _load_checkpoint(self) -> None:
        if self.est_path.exists():
            with self.est_path.open(newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    key = row.get("establishment_key")
                    if key:
                        self.done_keys.add(key)
        if self.checkpoint_path.exists():
            data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
            self.done_keys.update(data.get("done_keys", []))
            logging.info(
                "Resume: %d establishments already completed", len(self.done_keys)
            )

    def _save_checkpoint(self, page: int, note: str = "") -> None:
        payload = {
            "updated_at": _now(),
            "area": self.area,
            "city": self.city,
            "last_list_page": page,
            "done_count": len(self.done_keys),
            "stats": self.stats,
            "note": note,
            # Keep keys so resume works even if establishments.csv is moved.
            "done_keys": sorted(self.done_keys),
        }
        tmp = self.checkpoint_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(self.checkpoint_path)

    # --- HTTP / ASP.NET ------------------------------------------------------

    def sleep(self) -> None:
        pause = self.delay + random.uniform(0, self.jitter)
        time.sleep(max(0.0, pause))

    def _hidden_fields(self, soup: BeautifulSoup) -> Dict[str, str]:
        fields: Dict[str, str] = {}
        for inp in soup.select("input[name]"):
            name = inp.get("name")
            if not name:
                continue
            if name.endswith(".x") or name.endswith(".y"):
                continue
            fields[name] = inp.get("value") or ""
        return fields

    def request(
        self,
        method: str,
        url: str,
        data: Optional[Dict[str, str]] = None,
    ) -> BeautifulSoup:
        last_err: Optional[Exception] = None
        for attempt in range(1, self.retries + 1):
            try:
                self.sleep()
                resp = self.session.request(
                    method, url, data=data, timeout=90, allow_redirects=True
                )
                resp.raise_for_status()
                if "__VIEWSTATE" not in resp.text and "aspnetForm" not in resp.text:
                    raise RuntimeError("Unexpected response (missing ASP.NET form)")
                self.url = resp.url
                self.soup = BeautifulSoup(resp.text, "lxml")
                return self.soup
            except Exception as exc:  # noqa: BLE001 - retry any transient failure
                last_err = exc
                wait = min(60, 2 ** attempt)
                logging.warning(
                    "Request failed (%s/%s): %s; sleeping %ss",
                    attempt,
                    self.retries,
                    exc,
                    wait,
                )
                time.sleep(wait)
        raise RuntimeError(f"Request failed after retries: {last_err}")

    def get(self, url: str) -> BeautifulSoup:
        return self.request("GET", url)

    def postback(
        self,
        event_target: str,
        extra: Optional[Dict[str, str]] = None,
        url: Optional[str] = None,
    ) -> BeautifulSoup:
        assert self.soup is not None
        payload = self._hidden_fields(self.soup)
        if extra:
            payload.update(extra)
        payload["__EVENTTARGET"] = event_target
        payload["__EVENTARGUMENT"] = ""
        return self.request("POST", url or self.url, data=payload)

    def start_session(self) -> int:
        logging.info("Opening inspection portal…")
        self.get(LIST_URL)
        area_value = "--ANY--" if self.area.lower() in {"all", "--any--", ""} else self.area
        extra = {
            AREA_FILTER: area_value,
            CITY_FILTER: self.city if self.city else "--ANY--",
            "ctl00$PageContent$VW_EST_PUBLICSearch": "",
            "ctl00$PageContent$VW_EST_PUBLICSearch1": "",
        }
        self.postback(SEARCH_BUTTON, extra=extra)
        total = self._total_pages()
        logging.info(
            "Filter area=%r city=%r → %s pages (~%s establishments)",
            self.area,
            self.city or "(any)",
            total,
            total * 100,
        )
        return total

    def _total_pages(self) -> int:
        assert self.soup is not None
        el = self.soup.select_one(TOTAL_PAGES)
        if not el:
            return 1
        return int(el.get_text(strip=True) or "1")

    def _current_page(self) -> int:
        assert self.soup is not None
        el = self.soup.select_one(
            "#ctl00_PageContent_VW_EST_PUBLICPagination__CurrentPage"
        )
        if not el:
            return 1
        return int(el.get("value") or "1")

    def goto_page(self, page: int) -> None:
        if self._current_page() == page:
            return
        self.postback(
            GOTO_PAGE,
            extra={CURRENT_PAGE: str(page)},
        )
        if self._current_page() != page:
            # Fall back to stepping with Next
            while self._current_page() < page:
                self.postback(NEXT_PAGE)

    def next_page(self) -> None:
        self.postback(NEXT_PAGE)

    # --- Parsing -------------------------------------------------------------

    def parse_establishment_rows(self, list_page: int) -> List[EstablishmentRow]:
        assert self.soup is not None
        grid = self.soup.select_one("#VW_EST_PUBLICTableControlGrid")
        if not grid:
            return []
        rows: List[EstablishmentRow] = []
        for tr in grid.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 4:
                continue
            name = tds[1].get_text(" ", strip=True)
            address = tds[2].get_text(" ", strip=True)
            city = tds[3].get_text(" ", strip=True)
            link = tds[0].find("a", id=re.compile(r"InspButton"))
            if not name or not link:
                continue
            match = POSTBACK_RE.search(link.get("href") or "")
            if not match:
                continue
            # Row index from ctlNN in the event target
            m_idx = re.search(r"ctl(\d+)\$InspButton", match.group(1))
            row_index = int(m_idx.group(1)) if m_idx else len(rows)
            rows.append(
                EstablishmentRow(
                    name=name,
                    address=address,
                    city=city,
                    insp_target=match.group(1),
                    list_page=list_page,
                    row_index=row_index,
                )
            )
        return rows

    @staticmethod
    def parse_label_values(panel) -> Dict[str, str]:
        if panel is None:
            return {}
        out: Dict[str, str] = {}
        for tr in panel.find_all("tr"):
            label_td = tr.find("td", class_="fls")
            value_td = tr.find("td", class_="dfv")
            if not label_td or not value_td:
                continue
            label = label_td.get_text(" ", strip=True)
            value = value_td.get_text(" ", strip=True)
            if label:
                out[label] = value
        return out

    def parse_inspections(self) -> List[Tuple[Dict[str, str], Optional[str]]]:
        assert self.soup is not None
        grid = self.soup.select_one("#INSPECTIONTableControlGrid")
        if not grid:
            return []
        results: List[Tuple[Dict[str, str], Optional[str]]] = []
        seen: Set[str] = set()
        for tr in grid.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 4:
                continue
            cells = [td.get_text(" ", strip=True) for td in tds]
            # Typical: [Inspection Results, date, type, score, critical, noncritical]
            date = next((c for c in cells if DATE_RE.match(c)), None)
            if not date:
                continue
            # Find score-ish fields after the date
            try:
                date_i = cells.index(date)
            except ValueError:
                continue
            insp_type = cells[date_i + 1] if len(cells) > date_i + 1 else ""
            score = cells[date_i + 2] if len(cells) > date_i + 2 else ""
            critical = cells[date_i + 3] if len(cells) > date_i + 3 else ""
            noncritical = cells[date_i + 4] if len(cells) > date_i + 4 else ""
            dedupe = f"{date}|{insp_type}|{score}"
            if dedupe in seen:
                continue
            seen.add(dedupe)
            link = tr.find("a", id=re.compile(r"ViolButton"))
            target = None
            if link:
                m = POSTBACK_RE.search(link.get("href") or "")
                if m:
                    target = m.group(1)
            results.append(
                (
                    {
                        "inspection_date": date,
                        "inspection_type": insp_type,
                        "score": score,
                        "critical_violations": critical,
                        "noncritical_violations": noncritical,
                    },
                    target,
                )
            )
        return results

    def parse_violations(self) -> List[Dict[str, str]]:
        assert self.soup is not None
        grid = self.soup.select_one("#INSPECTION_VIOLATIONTableControlGrid")
        if not grid:
            return []
        rows: List[Dict[str, str]] = []
        for tr in grid.find_all("tr"):
            tds = tr.find_all("td", recursive=False)
            if len(tds) < 6:
                continue
            cells = [td.get_text(" ", strip=True) for td in tds]
            # Expected: code, observed, points, critical, occurrences, cos, phr
            code = cells[0]
            if not code or "Critical Violation" in code or code.startswith("Red Text"):
                continue
            # Skip continuation / legend rows
            if not re.match(r"^[\dA-Za-z].*", code):
                continue
            rows.append(
                {
                    "code": code,
                    "observed_violation": cells[1] if len(cells) > 1 else "",
                    "points": cells[2] if len(cells) > 2 else "",
                    "critical": cells[3] if len(cells) > 3 else "",
                    "occurrences": cells[4] if len(cells) > 4 else "",
                    "cos": cells[5] if len(cells) > 5 else "",
                    "phr": cells[6] if len(cells) > 6 else "",
                }
            )
        return rows

    # --- Scrape flow ---------------------------------------------------------

    def scrape_establishment(self, est: EstablishmentRow) -> None:
        list_url = self.url
        scraped_at = _now()

        self.postback(est.insp_target, url=list_url)
        if not self.soup or not self.soup.select_one("#INSPECTIONTableControlGrid"):
            raise RuntimeError(f"Failed to open inspections for {est.name}")

        details = self.parse_label_values(
            self.soup.select_one("#ctl00_PageContent_VW_EST_PUBLIC2RecordControlPanel")
        )
        inspections = self.parse_inspections()

        est_row = {
            "establishment_key": est.key,
            "name": details.get("Name") or est.name,
            "address": details.get("Address") or est.address,
            "city": est.city,
            "city_state_zip": details.get("City/State/ZIP", ""),
            "phone": details.get("Phone", ""),
            "establishment_type": details.get("Establishment Type", ""),
            "rank": details.get("Rank", ""),
            "list_page": est.list_page,
            "scraped_at": scraped_at,
        }
        insp_rows: List[Dict[str, Any]] = []
        viol_rows: List[Dict[str, Any]] = []

        for insp, viol_target in inspections:
            insp_rows.append(
                {
                    "establishment_key": est.key,
                    "name": est.name,
                    "scraped_at": scraped_at,
                    **insp,
                }
            )
            if self.skip_violations or not viol_target:
                continue

            # Drill into violation detail, then OK back to inspection list.
            self.postback(viol_target)
            for v in self.parse_violations():
                viol_rows.append(
                    {
                        "establishment_key": est.key,
                        "name": est.name,
                        "inspection_date": insp["inspection_date"],
                        "scraped_at": scraped_at,
                        **v,
                    }
                )
            self.postback(OK_BUTTON)

        # Back to establishment list
        self.postback(OK_BUTTON)
        if not self.soup.select_one("#VW_EST_PUBLICTableControlGrid"):
            # Recover by reloading list at this page
            logging.warning("Lost list page after %s; recovering…", est.name)
            total = self.start_session()
            self.goto_page(min(est.list_page, total))

        self._append_rows(
            self.est_path,
            [
                "establishment_key",
                "name",
                "address",
                "city",
                "city_state_zip",
                "phone",
                "establishment_type",
                "rank",
                "list_page",
                "scraped_at",
            ],
            [est_row],
        )
        self._append_rows(
            self.insp_path,
            [
                "establishment_key",
                "name",
                "inspection_date",
                "inspection_type",
                "score",
                "critical_violations",
                "noncritical_violations",
                "scraped_at",
            ],
            insp_rows,
        )
        self._append_rows(
            self.viol_path,
            [
                "establishment_key",
                "name",
                "inspection_date",
                "code",
                "observed_violation",
                "points",
                "critical",
                "occurrences",
                "cos",
                "phr",
                "scraped_at",
            ],
            viol_rows,
        )

        self.done_keys.add(est.key)
        self.stats["establishments"] += 1
        self.stats["inspections"] += len(insp_rows)
        self.stats["violations"] += len(viol_rows)

    def run(self) -> None:
        self.setup_output()
        total_pages = self.start_session()
        if self.max_pages:
            total_pages = min(total_pages, self.max_pages)

        # Resume near the earliest unfinished page if possible
        start_page = 1
        if self.done_keys and self.checkpoint_path.exists():
            try:
                data = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
                start_page = max(1, int(data.get("last_list_page", 1)))
            except (json.JSONDecodeError, TypeError, ValueError):
                start_page = 1

        if start_page > 1:
            logging.info("Jumping to list page %s", start_page)
            self.goto_page(start_page)

        processed = 0
        for page in range(start_page, total_pages + 1):
            if self._current_page() != page:
                self.goto_page(page)

            rows = self.parse_establishment_rows(page)
            logging.info("Page %s/%s — %s establishments", page, total_pages, len(rows))

            for est in rows:
                if est.key in self.done_keys:
                    self.stats["skipped"] += 1
                    continue
                if self.max_establishments is not None and processed >= self.max_establishments:
                    logging.info("Reached --max-establishments=%s", self.max_establishments)
                    self._save_checkpoint(page, note="max establishments reached")
                    return

                try:
                    logging.info(
                        "Scraping p%s/%s %s (%s, %s)",
                        page,
                        total_pages,
                        est.name,
                        est.address,
                        est.city,
                    )
                    self.scrape_establishment(est)
                    processed += 1
                    if processed % 10 == 0:
                        self._save_checkpoint(page)
                        logging.info("Progress %s", self.stats)
                except Exception as exc:  # noqa: BLE001
                    self.stats["errors"] += 1
                    logging.exception("Error on %s: %s", est.key, exc)
                    self._save_checkpoint(page, note=f"error on {est.key}")
                    # Rebuild session and continue
                    try:
                        self.start_session()
                        self.goto_page(page)
                    except Exception:
                        logging.exception("Failed to recover session; stopping")
                        raise

            self._save_checkpoint(page)
            if page < total_pages:
                self.next_page()

        self._save_checkpoint(total_pages, note="complete")
        logging.info("Done. %s", self.stats)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--out",
        type=Path,
        default=Path("data/slc"),
        help="Output directory for CSVs + checkpoint (default: data/slc)",
    )
    p.add_argument(
        "--area",
        default="Food Service",
        help='Inspection area filter (default: "Food Service"). Use "All" for every type.',
    )
    p.add_argument("--city", default="", help="Optional city filter, e.g. 'SALT LAKE CITY'")
    p.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Base seconds between requests (default: 1.5)",
    )
    p.add_argument(
        "--jitter",
        type=float,
        default=0.5,
        help="Extra random seconds added to each delay (default: 0.5)",
    )
    p.add_argument(
        "--skip-violations",
        action="store_true",
        help="Only scrape establishment + inspection summary rows (much faster)",
    )
    p.add_argument("--max-pages", type=int, default=None, help="Limit list pages (testing)")
    p.add_argument(
        "--max-establishments",
        type=int,
        default=None,
        help="Stop after N new establishments (testing)",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    log_path = args.out / "scrape.log"
    level = logging.DEBUG if args.verbose else logging.INFO
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    root = logging.getLogger()
    root.setLevel(level)
    # Avoid duplicate handlers if main() is called more than once (tests / re-runs).
    if not root.handlers:
        console = logging.StreamHandler()
        console.setFormatter(fmt)
        root.addHandler(console)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    logging.info("Logging to %s", log_path)
    scraper = SlcScraper(
        out_dir=args.out,
        area=args.area,
        city=args.city,
        delay=args.delay,
        jitter=args.jitter,
        skip_violations=args.skip_violations,
        max_pages=args.max_pages,
        max_establishments=args.max_establishments,
    )
    scraper.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
