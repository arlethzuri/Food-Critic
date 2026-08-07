"""DuckDB view over the merged inspection/violation CSV — the single data
source for Variant 1 (ReAct + CSV only, no RAG, no reviews)."""
import threading
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "processed" / "merged_food_inspections.csv"


class _LockedResult:
    """Wraps a DuckDB result so the connection lock stays held from
    execute() through the fetch call that consumes it."""

    def __init__(self, result, lock: threading.Lock):
        self._result = result
        self._lock = lock

    def __getattr__(self, name):
        attr = getattr(self._result, name)
        if not callable(attr):
            return attr

        def _fetch_and_release(*args, **kwargs):
            try:
                return attr(*args, **kwargs)
            finally:
                self._lock.release()

        return _fetch_and_release


class SafeConnection:
    """Serializes access to a single shared DuckDB connection.

    `@st.cache_resource` hands the same connection instance to every
    Streamlit session/rerun in the process, and DuckDB connections aren't
    safe for concurrent use from multiple threads — two reruns (e.g. two
    browser tabs, or a rerun overlapping the tail of a slow one) racing
    an `execute()`/`fetchdf()` pair against each other can corrupt the
    shared state (observed: a `fetchdf()` mid-race returning None instead
    of a DataFrame). This makes each execute-then-fetch pair atomic.
    """

    def __init__(self, con: duckdb.DuckDBPyConnection):
        self._con = con
        self._lock = threading.Lock()

    def execute(self, *args, **kwargs) -> _LockedResult:
        self._lock.acquire()
        try:
            result = self._con.execute(*args, **kwargs)
        except Exception:
            self._lock.release()
            raise
        return _LockedResult(result, self._lock)


def get_connection() -> SafeConnection:
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"{CSV_PATH} not found — run scripts/merge_food_inspections.py first."
        )
    con = duckdb.connect(database=":memory:")
    # ALL_VARCHAR: DuckDB's type-sniffer otherwise infers e.g. contact_info as
    # BIGINT (breaking formatted phone numbers) and inspection_score as
    # BIGINT (breaking empty-string filters) - keep every column text and
    # cast explicitly in queries, as documented in tools.SCHEMA_HELP.
    con.execute(
        f"CREATE VIEW inspections AS "
        f"SELECT * FROM read_csv_auto('{CSV_PATH.as_posix()}', ALL_VARCHAR=TRUE)"
    )
    return SafeConnection(con)
