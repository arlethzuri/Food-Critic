"""Price/Ratings/Cuisine/Health filter bar — View 1's filter row above the
map. Returns kwargs matching tools.search_establishments' own parameter
names, so the baseline view and the agent's own tool calls stay in the
same shape rather than duplicating filter logic."""
import streamlit as st


def render_filters(key_prefix: str) -> dict:
    cols = st.columns(4)
    with cols[0]:
        price_label = st.selectbox(
            "Price", ["Any", "$", "$$", "$$$", "$$$$"], key=f"{key_prefix}_filter_price"
        )
    with cols[1]:
        min_rating = st.slider(
            "Min rating", 1.0, 5.0, 1.0, 0.1, key=f"{key_prefix}_filter_rating"
        )
    with cols[2]:
        category = st.text_input(
            "Cuisine", placeholder="e.g. pizza, thai", key=f"{key_prefix}_filter_cuisine"
        )
    with cols[3]:
        health = st.selectbox(
            "Health",
            ["Any", "Has inspection data", "No inspection data on file"],
            key=f"{key_prefix}_filter_health",
            help="98.4% of establishments have no matched SLCHD inspection history — "
            "'Any' includes them, it doesn't imply a clean record.",
        )

    kwargs: dict = {}
    if price_label != "Any":
        kwargs["max_price_level"] = len(price_label)
    if min_rating > 1.0:
        kwargs["min_rating"] = min_rating
    if category:
        kwargs["category_contains"] = category
    if health == "Has inspection data":
        kwargs["require_inspection_data"] = True
    # No "exclude matched" filter on search_establishments itself — the
    # caller post-filters the returned rows for this one case.
    kwargs["exclude_matched"] = health == "No inspection data on file"
    return kwargs
