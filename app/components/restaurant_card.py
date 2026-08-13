"""Restaurant detail card (RESTAURANT_CARD_VIEW.JPG) — name/price/
rating/address/hours (no photo — no image data exists anywhere in the
pipeline, dropped per explicit decision), plus an expandable evidence
section when the last agent hypothesis concerns this establishment.
"""
import json

import streamlit as st

from components.establishment_format import address_preview, star_rating, today_day_label, todays_hours_batch
from components.reasoning_view import criteria_status
from schemas import HypothesisResponse
from tools import make_tools

_STATUS_ICON = {"good": "🟢", "warning": "🟡", "critical": "🔴"}


def _lookup(con, gmap_id: str) -> dict | None:
    tool_list = make_tools(con, chart_sink=[], candidate_sink=[])
    search = next(t for t in tool_list if t.name == "search_establishments")
    # gmap_id isn't a search_establishments filter — pull a wide name-agnostic
    # page and match locally. Fine at this data size; revisit if it grows.
    rows = json.loads(search.invoke({"limit": 500}))["rows"]
    return next((r for r in rows if r["gmap_id"] == gmap_id), None)


def render_restaurant_card(con, gmap_id: str, last_response: HypothesisResponse | None = None):
    row = _lookup(con, gmap_id)
    if row is None:
        st.warning("Establishment not found.")
        return

    with st.container(border=True):
        st.markdown(f"### {row['name']}")

        if row.get("avg_rating") is not None:
            avg_rating = row["avg_rating"]
            num_reviews = row.get("num_of_reviews")
            reviews_text = f" ({num_reviews:,})" if num_reviews is not None else ""
            rating_line = f"{avg_rating:.1f} {star_rating(avg_rating)}{reviews_text}"
        else:
            rating_line = "No rating"
        price = row.get("price") or "Price unknown"
        st.markdown(f"{rating_line}  ·  {price}")

        st.caption(f"📍 {address_preview(row['name'], row.get('address', ''))}")

        day_label = today_day_label()
        hours_span = todays_hours_batch(con, [gmap_id]).get(gmap_id)
        st.caption(f"🕐 {day_label}: {hours_span}" if hours_span else f"🕐 {day_label}: hours unknown")

        if not row.get("slchd_establishment_key"):
            st.caption("No matched SLCHD inspection history.")

        st.divider()
        st.markdown("**Evidence**")

        candidate = None
        if last_response is not None:
            candidate = next(
                (c for c in last_response.candidate_pool if c.gmap_id == gmap_id), None
            )

        if candidate is None:
            st.caption("No agent evidence for this establishment yet — ask about it in chat.")
            return

        for label, value, target, status in criteria_status(candidate):
            icon = _STATUS_ICON[status]
            target_text = f" (target {target:.1f})" if target is not None else ""
            st.write(f"{icon} **{label}:** {value:.1f}{target_text}")

        is_about_this = (
            last_response.establishment_name
            and last_response.establishment_name.strip().lower() == row["name"].strip().lower()
        )
        if is_about_this:
            for item in last_response.supporting_evidence + last_response.undermining_evidence:
                icon = "✅" if item.direction == "supports" else "⚠️"
                with st.expander(f"{icon} {item.relates_to_concept}"):
                    st.write(item.summary)
                    st.caption(item.source_ref)
