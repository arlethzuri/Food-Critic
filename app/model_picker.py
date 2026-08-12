"""Shared top-bar widget: provider dropdown, model dropdown scoped to
that provider, and a free-only filter checkbox. Used by all three
dashboards so each can pick a model independently. Rendered as a
horizontal row in the main area (not the sidebar) so the sidebar stays
free and the results/map/chat layout below gets the full window width.

`app/.env`'s LLM_PROVIDER/<PROVIDER>_MODEL still choose what's
pre-selected on first load; picking a different one here only changes
this session (returned explicitly, not written back to `.env` or
`os.environ` — see llm.get_llm's docstring for why: a Streamlit server
can serve multiple sessions from one process, so a global env var would
leak one user's choice into another's request).
"""
import os

import streamlit as st

from model_registry import PROVIDER_LABELS, PROVIDER_MODELS


def render_model_picker(key_prefix: str) -> tuple[str, str]:
    """Render the provider/model/free-only controls in a horizontal bar.

    Returns (provider, model_id) to pass straight to build_agent(...).
    """
    col_free, col_provider, col_model, col_warn = st.columns([1, 1, 1.5, 2])

    with col_free:
        free_only = st.checkbox(
            "Free models only",
            value=True,
            key=f"{key_prefix}_free_only",
            help="Hide models that cost money, or that technically work on a "
            "free key but have much tighter free-tier request quotas.",
        )

    providers = list(PROVIDER_MODELS)
    default_provider = os.getenv("LLM_PROVIDER", "groq").lower()
    default_index = providers.index(default_provider) if default_provider in providers else 0
    with col_provider:
        provider = st.selectbox(
            "Provider",
            providers,
            index=default_index,
            format_func=lambda p: PROVIDER_LABELS[p],
            key=f"{key_prefix}_provider",
        )

    all_models = PROVIDER_MODELS[provider]
    shown = [m for m in all_models if m["tier"] == "free"] if free_only else all_models
    if not shown:
        st.warning(f"No free models listed for {PROVIDER_LABELS[provider]} — showing all.")
        shown = all_models

    ids = [m["id"] for m in shown]
    default_model = os.getenv(f"{provider.upper()}_MODEL")
    model_index = ids.index(default_model) if default_model in ids else 0
    with col_model:
        # Keyed per-provider (and per-filter, since the option list differs
        # with free_only too) so switching provider/filter never leaves a
        # stale selection outside the new options list — Streamlit errors if
        # a widget's remembered session-state value isn't in `options`.
        model_id = st.selectbox(
            "Model",
            ids,
            index=model_index,
            format_func=lambda mid: next(m["label"] for m in shown if m["id"] == mid),
            key=f"{key_prefix}_{provider}_{free_only}_model",
        )

    tier = next(m["tier"] for m in shown if m["id"] == model_id)
    if tier == "paid":
        with col_warn:
            st.caption("⚠️ Paid, or a free key works but with a tight daily quota — check the provider's pricing page.")

    return provider, model_id
