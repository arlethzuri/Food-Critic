"""Wires the agent's search_establishments results back into the Explore
tab's results list/map. Without this, asking a question in chat only ever
lands the answer in the transcript below — the list/map above stay on
whatever the filter bar last produced, even though the agent may have
looked at a completely different set of establishments (e.g. "highest
rated in Provo" pulls Provo rows into candidate_sink, but the filter bar
has no city filter to reflect that).

Session-state keys are namespaced by key_prefix ('v1'/'v2'/'v3') so the
three dashboards don't collide.
"""
import streamlit as st


def record_chat_results(key_prefix: str, prompt: str, candidate_sink: list[dict]) -> None:
    """Call once, right after a successful agent run, before st.rerun().

    candidate_sink accumulates rows across every search_establishments
    call made during the turn (tools.py extends it per call, not
    per-question) — dedupe by gmap_id, keeping first-seen order, so a
    multi-call turn (e.g. broad search then a narrower follow-up) doesn't
    render the same restaurant as two cards.
    """
    if not candidate_sink:
        return
    seen: set[str] = set()
    deduped = []
    for row in candidate_sink:
        gid = row.get("gmap_id")
        if gid and gid not in seen:
            seen.add(gid)
            deduped.append(row)

    st.session_state[f"{key_prefix}_chat_rows"] = deduped
    st.session_state[f"{key_prefix}_chat_prompt"] = prompt

    selected_key = f"{key_prefix}_selected_gmap_id"
    if st.session_state.get(selected_key) not in seen:
        st.session_state[selected_key] = deduped[0]["gmap_id"]


def clear_chat_results(key_prefix: str) -> None:
    st.session_state.pop(f"{key_prefix}_chat_rows", None)
    st.session_state.pop(f"{key_prefix}_chat_prompt", None)


def resolve_display_rows(
    key_prefix: str, baseline_rows: list[dict], filter_kwargs: dict
) -> tuple[list[dict], str | None]:
    """(rows to show, active chat prompt or None if the view is filter-driven).

    A chat answer's results take over the list/map until either the user
    clears them explicitly or touches the filter bar — changing a filter
    is taken as an explicit "go back to browsing" signal, since otherwise
    the filter bar would visibly do nothing while a chat result is pinned.
    """
    snapshot_key = f"{key_prefix}_chat_filters_snapshot"
    prev_filters = st.session_state.get(snapshot_key)
    st.session_state[snapshot_key] = filter_kwargs
    if prev_filters is not None and prev_filters != filter_kwargs:
        clear_chat_results(key_prefix)

    chat_rows = st.session_state.get(f"{key_prefix}_chat_rows")
    if chat_rows:
        return chat_rows, st.session_state.get(f"{key_prefix}_chat_prompt")
    return baseline_rows, None
