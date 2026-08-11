"""Left-column restaurant result cards (View 1's R1/R2/... list) —
clicking one selects it, driving the map highlight and opening the
detail card (restaurant_card.py)."""
import streamlit as st


def render_results_list(rows: list[dict]) -> str | None:
    """Renders one card per establishment. Returns the gmap_id of
    whichever was clicked this rerun, or None."""
    if not rows:
        st.caption("No establishments match the current filters.")
        return None

    clicked = None
    for row in rows:
        rating = f"{row['avg_rating']:.1f}★" if row.get("avg_rating") is not None else "No rating"
        price = row.get("price") or ""
        badge = "" if row.get("slchd_establishment_key") else " · no inspection data"
        label = f"**{row['name']}**\n\n{rating}  {price}{badge}"
        if st.button(label, key=f"result_{row['gmap_id']}", use_container_width=True):
            clicked = row["gmap_id"]
    return clicked
