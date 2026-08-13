"""Baseline establishment map (View 1) — no reasoning overlay. See
reasoning_view.py for the per-step animated version (View 2A)."""
import pandas as pd
import plotly.express as px
import streamlit as st

# (max lat/lon span in degrees, zoom level) — first threshold the span
# fits under wins. Plotly's scatter_map (maplibre-based) takes a single
# zoom scalar with no fit-bounds helper for this trace type, so this is a
# lookup-table approximation of "frame the data", not a precise Mercator
# fit. Thresholds are eyeballed against Salt Lake County's ~0.3-0.5deg
# span (city-wide) vs. a single point (tightest).
_ZOOM_TABLE = [
    (0.01, 14.0), (0.02, 13.0), (0.05, 12.0), (0.1, 11.0),
    (0.2, 10.0), (0.5, 9.0), (1.0, 8.0), (2.0, 7.0),
]


def _auto_zoom(df: pd.DataFrame) -> float:
    if len(df) <= 1:
        return 14.0
    span = max(
        df["latitude"].max() - df["latitude"].min(),
        df["longitude"].max() - df["longitude"].min(),
    )
    for threshold, zoom in _ZOOM_TABLE:
        if span < threshold:
            return zoom
    return 6.0


def render_map(rows: list[dict], selected_gmap_id: str | None = None, height: int = 480):
    if not rows:
        st.info("No establishments match the current filters.")
        return

    df = pd.DataFrame(rows).dropna(subset=["latitude", "longitude"])
    if df.empty:
        st.info("No establishments with known coordinates match the current filters.")
        return

    df["Selected"] = df["gmap_id"].eq(selected_gmap_id) if selected_gmap_id else False
    fig = px.scatter_map(
        df,
        lat="latitude",
        lon="longitude",
        hover_name="name",
        hover_data={
            "avg_rating": ":.1f",
            "price": True,
            "latitude": False,
            "longitude": False,
            "Selected": False,
        },
        color="Selected",
        color_discrete_map={True: "#e6194B", False: "#4363d8"},
        zoom=_auto_zoom(df),
        height=height,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
