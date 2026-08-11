import csv
import os
import time
from pathlib import Path

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[3]
START_URL = "https://public.cdpehs.com/UTEnvPbl/VW_EST_PUBLIC/ShowVW_EST_PUBLICTablePage.aspx"
CSV_FILE = ROOT / "data" / "food_inspections.csv"
CHECKPOINT_FILE = ROOT / "scrape_checkpoint.txt"

# Result pages to scrape (1-indexed, inclusive). Each page holds ~100
# establishments. The site's own pager shows "of 118" total pages, so this
# range covers the last 43 pages.
START_PAGE = 76
END_PAGE = 118


def parse_detail_panel(page):
    """Parse the establishment info + inspection history panel that a click
    on an "Inspections" link swaps in for the results grid."""
    detail_soup = BeautifulSoup(page.content(), "html.parser")
    all_tables = detail_soup.find_all("table")

    def own_rows(table):
        # ASP.NET nests layout tables inside each other several levels deep,
        # and BeautifulSoup's find_all() recurses into descendants by
        # default - so rows must be scoped to direct ownership (nearest
        # table ancestor is this table), otherwise the same content gets
        # scraped once per nesting level (layout wrapper, footer, etc).
        return [tr for tr in table.find_all("tr") if tr.find_parent("table") is table]

    def row_cells(row):
        return [c.get_text(strip=True) for c in row.find_all(["td", "th"]) if c.find_parent("tr") is row]

    # The detail panel always has two real data blocks: an "Establishment
    # Information" key/value table, and an inspection history table whose
    # data rows start with the "Inspection Results" drill-down link. Target
    # those specifically instead of flattening every table on the page,
    # which also pulls in layout wrappers, nav chrome and the footer.
    est_keys = {"Name", "Address", "City/State/ZIP", "Phone", "Establishment Type", "Rank"}
    est_fields = {}
    inspection_rows = []
    seen_inspections = set()

    for table in all_tables:
        for d_row in own_rows(table):
            cells = row_cells(d_row)
            if len(cells) == 2 and cells[0] in est_keys:
                est_fields.setdefault(cells[0], cells[1])
            elif len(cells) >= 2 and cells[0] == "Inspection Results":
                key = tuple(cells)
                if key not in seen_inspections:
                    seen_inspections.add(key)
                    inspection_rows.append(cells[1:])

    return est_fields, inspection_rows, detail_soup


def write_record(writer, csv_f, est_info, est_type, data_str):
    writer.writerow([est_info, est_type, data_str])
    csv_f.flush()


def scrape_food_inspections():
    start_page = START_PAGE
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as cf:
            last_done = int(cf.read().strip())
        start_page = last_done + 1
        print(f"Resuming from page {start_page} (last completed page: {last_done})")

    if start_page > END_PAGE:
        print(f"Nothing to do - checkpoint already covers pages up to {END_PAGE}.")
        return

    file_exists = os.path.exists(CSV_FILE)
    csv_f = open(CSV_FILE, "a", newline="", encoding="utf-8")
    writer = csv.writer(csv_f)
    if not file_exists:
        writer.writerow(["Establishment", "Establishment Type", "Inspection Data"])
        csv_f.flush()

    total_rows_written = 0

    with sync_playwright() as p:
        # Headless for this run - it's a long unattended job (many pages),
        # and headless is faster/more stable than a visible window.
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("Navigating to search page...")
        page.goto(START_URL)
        page.wait_for_load_state("networkidle")
        time.sleep(2)

        search_button_id = "ctl00_PageContent_VW_EST_PUBLICSearchButton__Button"
        search_locator = page.locator(f"#{search_button_id}")

        print("Clicking 'Start Search' to pull results...")
        if search_locator.count() > 0:
            search_locator.click()
        else:
            print("ID locator failed, trying text-based fallback...")
            page.get_by_role("link", name="Start Search", exact=True).click()

        print("Waiting for search results to load...")
        page.wait_for_load_state("networkidle")
        time.sleep(4)  # Give the Ajax elements plenty of time to populate

        if start_page != 1:
            print(f"Jumping directly to page {start_page}...")
            # The page-number box only submits on a real Enter keypress
            # (it has a client-side onkeypress handler wired to the postback) -
            # a plain .fill() + separate button click does not trigger it.
            page_input = page.locator("#ctl00_PageContent_VW_EST_PUBLICPagination__CurrentPage")
            page_input.click()
            page_input.fill("")
            page_input.type(str(start_page))
            page_input.press("Enter")
            page.wait_for_load_state("networkidle")
            time.sleep(2)

        page_num = start_page

        print(f"\n--- STAGE 1 & 2: HARVESTING & PARSING DETAILS (pages {start_page}-{END_PAGE}) ---")

        while page_num <= END_PAGE:
            print(f"\n--- Processing Page {page_num} ---")

            # Direct targeting: This only matches actual "Inspections" buttons (bypasses layout rows)
            insp_links_locator = page.locator("a[id*='InspButton']")
            link_count = insp_links_locator.count()
            print(f"Found {link_count} establishment records on current page.")

            # Loop through each actual establishment row button.
            # NOTE: clicking an "Inspections" link does an in-place AJAX (UpdatePanel)
            # postback that replaces the results grid with a detail panel - it never
            # opens a new tab/page. So after scraping the detail panel we must click
            # the "Back" button to restore the results grid before moving to the
            # next row.
            for i in range(link_count):
                try:
                    link_loc = insp_links_locator.nth(i)

                    print(f"[{i+1}/{link_count}] Opening inspection history...")

                    # Click triggers the async UpdatePanel postback in place.
                    link_loc.click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(1.5)  # Let Ajax-rendered detail content settle

                    est_fields, inspection_rows, detail_soup = parse_detail_panel(page)
                    est_info = est_fields.get("Name", f"Establishment Row {i+1}")
                    est_type = est_fields.get("Establishment Type", "")
                    print(f"   -> {est_info}")

                    if est_fields:
                        other_fields = {k: v for k, v in est_fields.items() if k != "Establishment Type"}
                        write_record(
                            writer, csv_f, est_info, est_type,
                            " | ".join(f"{k}: {v}" for k, v in other_fields.items()),
                        )
                        total_rows_written += 1

                    labels = ["Date", "Inspection Type", "Score", "Critical Violations", "Non-Critical Violations"]
                    for insp in inspection_rows:
                        pairs = [f"{lbl}: {val}" for lbl, val in zip(labels, insp)]
                        write_record(writer, csv_f, est_info, est_type, " | ".join(pairs))
                        total_rows_written += 1

                    # Fallback if the expected structures weren't found
                    if not est_fields and not inspection_rows:
                        content_text = detail_soup.get_text(separator=" | ", strip=True)
                        write_record(writer, csv_f, est_info, est_type, content_text[:500])
                        total_rows_written += 1

                    # Return to the results grid for the next iteration
                    page.locator("#ctl00_PageContent_OKButton__Button").click()
                    page.wait_for_load_state("networkidle")
                    time.sleep(1.5)  # Let the results grid re-render

                    # Rate limiting delay
                    time.sleep(1)

                except Exception as err:
                    print(f"   [Error processing record {i+1}]: {err}")
                    # Safety recovery: try to get back to the results grid if a
                    # single item crashes mid-flow.
                    try:
                        back_btn = page.locator("#ctl00_PageContent_OKButton__Button")
                        if back_btn.count() > 0 and back_btn.is_visible():
                            back_btn.click()
                            page.wait_for_load_state("networkidle")
                            time.sleep(1.5)
                    except Exception:
                        pass

            # Page fully processed - checkpoint so a crash later doesn't
            # cost us this page's work too.
            with open(CHECKPOINT_FILE, "w", encoding="utf-8") as cf:
                cf.write(str(page_num))

            if page_num >= END_PAGE:
                print(f"\nReached target end page ({END_PAGE}).")
                break

            # --- PAGINATION ---
            next_button = page.get_by_role("link", name="Next", exact=False)
            if next_button.count() > 0 and next_button.is_visible():
                print("\nMoving to next page of establishments...")
                next_button.click()
                page.wait_for_load_state("networkidle")
                time.sleep(3)  # Wait for dynamic refresh
                page_num += 1
            else:
                print("\nNo further pages found.")
                break

        csv_f.close()
        print(f"\nSuccess! Appended {total_rows_written} rows of inspections to '{CSV_FILE}'")
        browser.close()


if __name__ == "__main__":
    scrape_food_inspections()
