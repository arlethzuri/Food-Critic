"""Left-column restaurant result cards (View 1's R1/R2/... list) —
clicking one selects it, driving the map highlight and opening the
detail card (restaurant_card.py)."""
import streamlit as st

from components.establishment_format import address_preview, star_rating, today_day_label, todays_hours_batch


def render_results_list(con, rows: list[dict]) -> str | None:
    """Renders one card per establishment. Returns the gmap_id of
    whichever was clicked this rerun, or None."""
    if not rows:
        st.caption("No establishments match the current filters.")
        return None

    day_label = today_day_label()
    hours_by_id = todays_hours_batch(con, [row["gmap_id"] for row in rows])

    clicked = None
    for row in rows:
        if row.get("avg_rating") is not None:
            rating = f"{row['avg_rating']:.1f} {star_rating(row['avg_rating'])}"
        else:
            rating = "No rating"
        price = row.get("price") or ""
        badge = "" if row.get("slchd_establishment_key") else " · no inspection data"
        addr = address_preview(row["name"], row.get("address", ""))
        hours_span = hours_by_id.get(row["gmap_id"])
        hours_text = f"{day_label}: {hours_span}" if hours_span else f"{day_label}: hours unknown"
        label = f"**{row['name']}**\n\n{rating}  {price}{badge}\n\n📍 {addr}\n\n🕐 {hours_text}"
        if st.button(label, key=f"result_{row['gmap_id']}", use_container_width=True):
            clicked = row["gmap_id"]
    return clicked
