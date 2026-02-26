"""Patrol DB — SQLite database for patrol runs and inspection results.

Stores patrol run metadata, per-point inspection results, and token usage
breakdown.  The schema is compatible with visual-patrol v1's patrol.db
(simplified: no robot_id, robot_serial, sync_status, robot_moving_status).
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from config import DATA_DIR

DB_FILE = os.path.join(DATA_DIR, "patrol.db")

# ---------------------------------------------------------------------------
# Connection & context manager
# ---------------------------------------------------------------------------


def _connect() -> sqlite3.Connection:
    """Open a connection with WAL mode, busy timeout, and Row factory."""
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_FILE, timeout=10)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_context():
    """Context manager that auto-commits on success and rolls back on error."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Schema initialisation
# ---------------------------------------------------------------------------

_CREATE_PATROL_RUNS = """
CREATE TABLE IF NOT EXISTS patrol_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    start_time       TEXT    NOT NULL,
    end_time         TEXT,
    status           TEXT    NOT NULL DEFAULT 'Running',
    report_content   TEXT,
    model_id         TEXT,
    video_path       TEXT,
    video_analysis   TEXT,

    -- Token usage: overall
    input_tokens         INTEGER NOT NULL DEFAULT 0,
    output_tokens        INTEGER NOT NULL DEFAULT 0,
    total_tokens         INTEGER NOT NULL DEFAULT 0,

    -- Token usage: report generation
    report_input_tokens  INTEGER NOT NULL DEFAULT 0,
    report_output_tokens INTEGER NOT NULL DEFAULT 0,
    report_total_tokens  INTEGER NOT NULL DEFAULT 0,

    -- Token usage: video analysis
    video_input_tokens   INTEGER NOT NULL DEFAULT 0,
    video_output_tokens  INTEGER NOT NULL DEFAULT 0,
    video_total_tokens   INTEGER NOT NULL DEFAULT 0
)
"""

_CREATE_INSPECTION_RESULTS = """
CREATE TABLE IF NOT EXISTS inspection_results (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id         INTEGER NOT NULL,
    point_name     TEXT    NOT NULL,
    coordinate_x   REAL,
    coordinate_y   REAL,
    prompt         TEXT,
    ai_response    TEXT,
    is_ng          INTEGER NOT NULL DEFAULT 0,
    ai_description TEXT,
    image_path     TEXT,
    timestamp      TEXT    NOT NULL,

    -- Token usage per inspection
    input_tokens   INTEGER NOT NULL DEFAULT 0,
    output_tokens  INTEGER NOT NULL DEFAULT 0,
    total_tokens   INTEGER NOT NULL DEFAULT 0,

    FOREIGN KEY (run_id) REFERENCES patrol_runs(id)
)
"""


def init_db():
    """Create tables if they do not exist yet."""
    with db_context() as conn:
        conn.execute(_CREATE_PATROL_RUNS)
        conn.execute(_CREATE_INSPECTION_RESULTS)


# ---------------------------------------------------------------------------
# CRUD — patrol_runs
# ---------------------------------------------------------------------------


def create_run(start_time: str = "", model_id: str = "") -> int:
    """Insert a new patrol run and return its id."""
    if not start_time:
        start_time = datetime.now().isoformat()
    with db_context() as conn:
        cur = conn.execute(
            "INSERT INTO patrol_runs (start_time, model_id) VALUES (?, ?)",
            (start_time, model_id),
        )
        return cur.lastrowid


def update_run(run_id: int, **fields) -> None:
    """Update arbitrary columns on a patrol run.

    Usage::

        update_run(run_id, status="Completed", end_time=datetime.now().isoformat())
    """
    if not fields:
        return
    allowed = {
        "start_time", "end_time", "status", "report_content", "model_id",
        "video_path", "video_analysis",
        "input_tokens", "output_tokens", "total_tokens",
        "report_input_tokens", "report_output_tokens", "report_total_tokens",
        "video_input_tokens", "video_output_tokens", "video_total_tokens",
    }
    keys = [k for k in fields if k in allowed]
    if not keys:
        return
    set_clause = ", ".join(f"{k} = ?" for k in keys)
    values = [fields[k] for k in keys]
    values.append(run_id)
    with db_context() as conn:
        conn.execute(
            f"UPDATE patrol_runs SET {set_clause} WHERE id = ?",
            values,
        )


def get_run(run_id: int) -> dict | None:
    """Return a single patrol run as a dict, or None."""
    with db_context() as conn:
        row = conn.execute(
            "SELECT * FROM patrol_runs WHERE id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None


def get_runs(*, limit: int = 50, offset: int = 0) -> list[dict]:
    """Return patrol runs ordered by start_time descending."""
    with db_context() as conn:
        rows = conn.execute(
            "SELECT * FROM patrol_runs ORDER BY start_time DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]


def get_run_count() -> int:
    """Return total number of patrol runs."""
    with db_context() as conn:
        row = conn.execute("SELECT COUNT(*) FROM patrol_runs").fetchone()
        return row[0]


# ---------------------------------------------------------------------------
# CRUD — inspection_results
# ---------------------------------------------------------------------------


def insert_inspection(
    *,
    run_id: int,
    point_name: str,
    coordinate_x: float | None = None,
    coordinate_y: float | None = None,
    prompt: str | None = None,
    ai_response: str | None = None,
    is_ng: int = 0,
    ai_description: str | None = None,
    image_path: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    total_tokens: int = 0,
) -> int:
    """Insert an inspection result and return its id."""
    with db_context() as conn:
        cur = conn.execute(
            """
            INSERT INTO inspection_results
                (run_id, point_name, coordinate_x, coordinate_y, prompt,
                 ai_response, is_ng, ai_description, image_path, timestamp,
                 input_tokens, output_tokens, total_tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id, point_name, coordinate_x, coordinate_y, prompt,
                ai_response, is_ng, ai_description, image_path,
                datetime.now().isoformat(),
                input_tokens, output_tokens, total_tokens,
            ),
        )
        return cur.lastrowid


def get_inspections(run_id: int) -> list[dict]:
    """Return all inspection results for a given run, ordered by timestamp."""
    with db_context() as conn:
        rows = conn.execute(
            "SELECT * FROM inspection_results WHERE run_id = ? ORDER BY timestamp",
            (run_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_inspections_by_date(start_date: str, end_date: str) -> list[dict]:
    """Return inspections within a date range.

    Args:
        start_date: Start date string (e.g. '2026-02-25')
        end_date: End date string (e.g. '2026-02-28')
    """
    with db_context() as conn:
        rows = conn.execute(
            "SELECT ir.*, pr.start_time as run_start "
            "FROM inspection_results ir "
            "JOIN patrol_runs pr ON ir.run_id = pr.id "
            "WHERE pr.start_time >= ? AND pr.start_time <= ? "
            "ORDER BY ir.timestamp",
            (start_date, end_date + " 23:59:59"),
        ).fetchall()
        return [dict(r) for r in rows]


def get_daily_token_stats() -> list[dict]:
    """Return daily aggregated token usage from patrol_runs.

    Returns a list of dicts with keys: date, input, output, total.
    """
    with db_context() as conn:
        rows = conn.execute(
            "SELECT DATE(start_time) as date, "
            "SUM(input_tokens) as input, "
            "SUM(output_tokens) as output, "
            "SUM(total_tokens) as total "
            "FROM patrol_runs "
            "WHERE start_time IS NOT NULL AND start_time != '' "
            "GROUP BY DATE(start_time) "
            "ORDER BY date"
        ).fetchall()
        return [dict(r) for r in rows]
