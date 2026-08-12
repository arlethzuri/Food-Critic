"""Read-only DuckDB connection to db/food_health.duckdb — the normalized
schema (establishments, establishment_keys, inspections, violations,
violation_codes, review, category, ...) built by scripts/load_duckdb.py.
Single data source for all three dashboard variants."""
import threading
from pathlib import Path

import duckdb

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "food_health.duckdb"


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
    if not DB_PATH.exists():
        raise FileNotFoundError(
            f"{DB_PATH} not found — run scripts/load_duckdb.py first."
        )
    con = duckdb.connect(database=str(DB_PATH), read_only=True)
    con.execute("INSTALL spatial; LOAD spatial;")
    return SafeConnection(con)
