"""Display formatting shared by the results list and the detail card —
star glyphs, a de-duplicated address line, and today's hours off
gmap_hours — so the two views can't drift apart on how they render the
same establishment.
"""
import datetime

_DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def star_rating(rating: float) -> str:
    """Nearest-whole-star glyph string — matches how the reference Google
    Maps card renders e.g. 4.1 as 4 filled + 1 empty, not a half-star split."""
    filled = max(0, min(5, round(rating)))
    return "★" * filled + "☆" * (5 - filled)


def address_preview(name: str, address: str | None) -> str:
    """establishments.address is stored as '{name}, {street}, {city}, {state} {zip}'
    (the scrape source repeats the name) — strip that prefix so the caption
    isn't just echoing the name shown right next to it. address is nullable
    in the schema, so a row can have it present but SQL NULL."""
    if not address:
        return "Address unknown"
    prefix = f"{name}, "
    if address.lower().startswith(prefix.lower()):
        return address[len(prefix):]
    return address


def _format_clock(ms: int) -> str:
    total_min = (ms // 60_000) % (24 * 60)
    h, m = divmod(total_min, 60)
    period = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{m:02d} {period}" if m else f"{h12} {period}"


def today_day_label() -> str:
    gmap_day = (datetime.date.today().weekday() + 1) % 7  # gmap_hours.day: 0=Sun..6=Sat
    return _DAY_NAMES[gmap_day]


def todays_hours_batch(con, gmap_ids: list[str]) -> dict[str, str | None]:
    """{gmap_id: 'open – close' span for today's real weekday, or None if
    closed/no data} for every id in gmap_ids, in one query — the results
    list needs this per-row for up to 200 rows, so a per-row query isn't
    an option. Hours come from the establishment's recurring weekly
    schedule, not a live feed, so this is 'scheduled hours' rather than
    an 'Open now' claim that could be stale."""
    if not gmap_ids:
        return {}
    gmap_day = (datetime.date.today().weekday() + 1) % 7
    rows = con.execute(
        "SELECT gmap_id, open_min, open_max FROM gmap_hours "
        "WHERE day = $day AND gmap_id IN (SELECT UNNEST($ids))",
        {"day": gmap_day, "ids": gmap_ids},
    ).fetchall()
    return {
        gmap_id: f"{_format_clock(open_min)} – {_format_clock(open_max)}"
        for gmap_id, open_min, open_max in rows
        if open_min is not None and open_max is not None
    }
