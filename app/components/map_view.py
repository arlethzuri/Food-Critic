"""Baseline establishment map (View 1) — no reasoning overlay. See
reasoning_view.py for the per-step animated version (View 2A)."""
import pandas as pd
import plotly.express as px
import streamlit as st


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
        zoom=10,
        height=height,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
    st.plotly_chart(fig, use_container_width=True)
