"""Schema versioning and migrations for the four persistence tables.

Tables:
- ``jobs``: one row per split job, the job-level state and config snapshot
- ``clips``: one row per clip within a job, per-clip state and counters
- ``attempts``: append-only attempt log, one row per FFmpeg run or ladder step
- ``events``: append-only event log, one row per state change or milestone

Schema version is tracked via ``PRAGMA user_version``, starting at 1.
Migrations are additive; the database never rewrites history.
"""

from __future__ import annotations

import sqlite3
from typing import cast

SCHEMA_VERSION = 1

_SCHEMA_SQL = """
-- Jobs: one row per split job
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    input_path TEXT NOT NULL,
    output_dir TEXT NOT NULL,
    state TEXT NOT NULL,
    total_clips INTEGER NOT NULL DEFAULT 0,
    completed_clips INTEGER NOT NULL DEFAULT 0,
    failed_clips INTEGER NOT NULL DEFAULT 0,
    review_clips INTEGER NOT NULL DEFAULT 0,
    config_snapshot TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

-- Clips: one row per clip within a job
CREATE TABLE IF NOT EXISTS clips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    "index" INTEGER NOT NULL,
    start_us INTEGER NOT NULL,
    duration_us INTEGER NOT NULL,
    state TEXT NOT NULL,
    output_path TEXT,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    size_attempts INTEGER NOT NULL DEFAULT 0,
    fault_retries INTEGER NOT NULL DEFAULT 0,
    total_encodes INTEGER NOT NULL DEFAULT 0,
    two_pass INTEGER NOT NULL DEFAULT 0,
    crf INTEGER NOT NULL DEFAULT 32,
    error_message TEXT,
    degradation TEXT NOT NULL DEFAULT '[]',
    quality_metric TEXT,
    quality_score REAL,
    quality_threshold REAL,
    UNIQUE(job_id, "index")
);

-- Attempts: append-only attempt log (RULE-24: append-only)
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    clip_index INTEGER NOT NULL,
    attempt_number INTEGER NOT NULL,
    type TEXT NOT NULL,
    result TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    crf INTEGER,
    duration_seconds REAL,
    stderr_tail TEXT,
    created_at REAL NOT NULL
);

-- Events: append-only event log
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    clip_index INTEGER,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_clips_job ON clips(job_id);
CREATE INDEX IF NOT EXISTS idx_attempts_job ON attempts(job_id);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id);
"""

_JOBS_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_input_output ON jobs(input_path, output_dir);
"""


def init_schema(conn: sqlite3.Connection) -> int:
    """Create tables if missing and ensure schema is at the current version.

    Returns the schema version after migration.
    """
    conn.executescript(_SCHEMA_SQL)
    conn.execute(_JOBS_INDEX)
    current = cast(int, conn.execute("PRAGMA user_version").fetchone()[0])
    if current < SCHEMA_VERSION:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        current = SCHEMA_VERSION
    return current


def schema_version(conn: sqlite3.Connection) -> int:
    """Return the current PRAGMA user_version."""
    return cast(int, conn.execute("PRAGMA user_version").fetchone()[0])


def migrate(conn: sqlite3.Connection, target: int) -> None:
    """Placeholder for future additive migrations.

    All migrations from version 1 forward go here. Each migration runs inside
    the caller's transaction; a failure rolls back the whole batch.
    """
    current = schema_version(conn)
    if current >= target:
        return
    # Additive migrations are written here as they are needed.
    # Each block: if current < N: run DDL; PRAGMA user_version = N
    conn.execute(f"PRAGMA user_version = {target}")
