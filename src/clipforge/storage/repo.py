"""Repository: insert job, update clip state, append attempt, log event, load job.

All writes go through the transactional connection from `storage.db`. Every
state change commits to the database before the corresponding filesystem
mutation happens (RULE-22).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from clipforge.core.constants import ClipState, JobState
from clipforge.storage.db import connect


def _now() -> float:
    return time.time()


def create_job(
    db_path: Path,
    input_path: Path,
    output_dir: Path,
    config_snapshot: dict[str, object],
) -> int:
    """Insert a job row and return its new id."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO jobs (input_path, output_dir, state, total_clips,
                              completed_clips, failed_clips, review_clips,
                              config_snapshot, created_at, updated_at)
            VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?, ?)
            """,
            (
                str(input_path),
                str(output_dir),
                JobState.PENDING.value,
                0,
                json.dumps(config_snapshot, sort_keys=True),
                _now(),
                _now(),
            ),
        )
        return int(cur.lastrowid if cur.lastrowid is not None else 0)


def load_job(db_path: Path, job_id: int) -> dict[str, object] | None:
    """Load a job row as a dict, or None when it does not exist."""
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, input_path, output_dir, state, total_clips,
                   completed_clips, failed_clips, review_clips,
                   config_snapshot, created_at, updated_at
            FROM jobs WHERE id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "input_path": row[1],
        "output_dir": row[2],
        "state": row[3],
        "total_clips": row[4],
        "completed_clips": row[5],
        "failed_clips": row[6],
        "review_clips": row[7],
        "config_snapshot": json.loads(row[8]),
        "created_at": row[9],
        "updated_at": row[10],
    }


def set_job_state(db_path: Path, job_id: int, state: JobState) -> None:
    """Update a job's state and bump updated_at."""
    with connect(db_path) as conn:
        conn.execute(
            "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
            (state.value, _now(), job_id),
        )


def set_job_counts(
    db_path: Path,
    job_id: int,
    total: int,
    completed: int,
    failed: int,
    review: int,
) -> None:
    """Update the job's clip counters."""
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE jobs
            SET total_clips = ?, completed_clips = ?, failed_clips = ?,
                review_clips = ?, updated_at = ?
            WHERE id = ?
            """,
            (total, completed, failed, review, _now(), job_id),
        )


def insert_clip(
    db_path: Path,
    job_id: int,
    index: int,
    start_us: int,
    duration_us: int,
) -> int:
    """Insert a clip row in PENDING state and return its new id."""
    with connect(db_path) as conn:
        cur = conn.execute(
            """
            INSERT INTO clips (job_id, "index", start_us, duration_us, state,
                               size_bytes, size_attempts, fault_retries,
                               total_encodes, two_pass, crf, degradation,
                               quality_metric, quality_score, quality_threshold)
            VALUES (?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 32, '[]', NULL, NULL, NULL)
            """,
            (job_id, index, start_us, duration_us, ClipState.PENDING.value),
        )
        return int(cur.lastrowid if cur.lastrowid is not None else 0)


def update_clip_state(
    db_path: Path,
    job_id: int,
    index: int,
    state: ClipState,
    output_path: Path | None = None,
    size_bytes: int = 0,
    size_attempts: int = 0,
    fault_retries: int = 0,
    total_encodes: int = 0,
    two_pass: bool = False,
    crf: int = 32,
    error_message: str | None = None,
    degradation: tuple[str, ...] = (),
    quality_metric: str | None = None,
    quality_score: float | None = None,
    quality_threshold: float | None = None,
) -> None:
    """Update a clip row with current state and counters (append-only via attempts)."""
    with connect(db_path) as conn:
        conn.execute(
            """
            UPDATE clips
            SET state = ?, output_path = ?, size_bytes = ?,
                size_attempts = ?, fault_retries = ?, total_encodes = ?,
                two_pass = ?, crf = ?, error_message = ?,
                degradation = ?, quality_metric = ?, quality_score = ?,
                quality_threshold = ?
            WHERE job_id = ? AND "index" = ?
            """,
            (
                state.value,
                str(output_path) if output_path else None,
                size_bytes,
                size_attempts,
                fault_retries,
                total_encodes,
                1 if two_pass else 0,
                crf,
                error_message,
                json.dumps(list(degradation)),
                quality_metric,
                quality_score,
                quality_threshold,
                job_id,
                index,
            ),
        )


def append_attempt(
    db_path: Path,
    job_id: int,
    clip_index: int,
    attempt_number: int,
    type: str,
    result: str,
    size_bytes: int = 0,
    crf: int | None = None,
    duration_seconds: float | None = None,
    stderr_tail: str = "",
) -> None:
    """Append an attempt row (append-only; never updates or deletes old rows - RULE-24)."""
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO attempts (job_id, clip_index, attempt_number, type, result,
                                  size_bytes, crf, duration_seconds, stderr_tail, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                clip_index,
                attempt_number,
                type,
                result,
                size_bytes,
                crf,
                duration_seconds,
                stderr_tail,
                _now(),
            ),
        )


def log_event(
    db_path: Path,
    job_id: int,
    event_type: str,
    message: str,
    clip_index: int | None = None,
) -> None:
    """Append an event row."""
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO events (job_id, clip_index, event_type, message, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, clip_index, event_type, message, _now()),
        )


def load_job_clips(db_path: Path, job_id: int) -> list[dict[str, object]]:
    """Load all clip rows for a job, ordered by index."""
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT "index", start_us, duration_us, state, output_path, size_bytes,
                   size_attempts, fault_retries, total_encodes, two_pass, crf,
                   error_message, degradation, quality_metric, quality_score,
                   quality_threshold
            FROM clips WHERE job_id = ?
            ORDER BY "index"
            """,
            (job_id,),
        ).fetchall()
    return [
        {
            "index": r[0],
            "start_us": r[1],
            "duration_us": r[2],
            "state": r[3],
            "output_path": r[4],
            "size_bytes": r[5],
            "size_attempts": r[6],
            "fault_retries": r[7],
            "total_encodes": r[8],
            "two_pass": bool(r[9]),
            "crf": r[10],
            "error_message": r[11],
            "degradation": json.loads(r[12]),
            "quality_metric": r[13],
            "quality_score": r[14],
            "quality_threshold": r[15],
        }
        for r in rows
    ]


def reset_in_flight_clips(db_path: Path, job_id: int) -> int:
    """Reset any clip in an in-flight state back to PENDING (crash recovery).

    Returns the number of clips reset.
    """
    in_flight = ",".join(f"'{s.value}'" for s in ClipState if s.value in {
        "ENCODING", "VERIFYING", "RETRYING",
    })
    with connect(db_path) as conn:
        cur = conn.execute(
            f"""
            UPDATE clips SET state = ? WHERE job_id = ? AND state IN ({in_flight})
            """,
            (ClipState.PENDING.value, job_id),
        )
        return int(cur.rowcount)


def job_exists(db_path: Path, input_path: Path, output_dir: Path) -> tuple[int, str] | None:
    """Return an existing job id for the same input+output, or None."""
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT id, state FROM jobs WHERE input_path = ? AND output_dir = ?
            ORDER BY id DESC LIMIT 1
            """,
            (str(input_path), str(output_dir)),
        ).fetchone()
    if row is None:
        return None
    return int(row[0]), row[1]
