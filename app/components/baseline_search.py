"""Baseline (non-agent) establishment search for View 1's results
list/map — reuses tools.search_establishments directly so the filter bar
and the agent's own searches share one query implementation, not two
that can drift apart."""
import json

from tools import make_tools


def search_baseline(con, **filter_kwargs) -> list[dict]:
    exclude_matched = filter_kwargs.pop("exclude_matched", False)
    tool_list = make_tools(con, chart_sink=[], candidate_sink=[])
    search = next(t for t in tool_list if t.name == "search_establishments")
    result = json.loads(search.invoke({**filter_kwargs, "limit": 200}))
    rows = result["rows"]
    if exclude_matched:
        rows = [r for r in rows if not r.get("slchd_establishment_key")]
    return rows
