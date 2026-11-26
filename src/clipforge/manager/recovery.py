"""Resume and crash-recovery logic (Phase 9, FR-RES-01 to FR-RES-07, RULE-22).

Turns the Phase 8 memory (SQLite job row, per-clip state, manifest) into
behavior: an interrupted job resumes exactly where it stopped, without
re-encoding finished clips or losing any that were in flight.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import cast

from clipforge.core.constants import ClipState, JobState
from clipforge.storage.db import connect
from clipforge.storage.repo import (
    job_exists,
    load_job_clips,
    reset_in_flight_clips,
    set_job_state,
)


def fingerprint_file(path: Path) -> str:
    """SHA-256 hex digest of the whole file, used for duplicate detection.

    Reads in bounded chunks so multi-gigabyte inputs never load into memory.
    """
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def prepare_resume(
    db_path: Path, input_path: Path, output_dir: Path
) -> tuple[int, list[dict[str, object]]]:
    """Prepare an interrupted job for resume.

    Loads the existing job row, resets any in-flight clips back to PENDING,
    and marks clips whose output file vanished as PENDING again (so they get
    re-encoded). Completed clips with intact files are left untouched
    (RULE-66).

    Returns the job id and the list of clip dicts to process (those still
    PENDING after reset), in index order.
    """
    found = job_exists(db_path, input_path, output_dir)
    if found is None:
        raise FileNotFoundError(f"no job for {input_path} -> {output_dir}")
    job_id, _state = found

    # Re-open the job as PROCESSING so a second run can continue
    set_job_state(db_path, job_id, JobState.PROCESSING)

    # Reset clips left in-flight by a crash (ENCODING / VERIFYING / RETRYING)
    reset_in_flight_clips(db_path, job_id)

    # Reload clips after reset
    clips = load_job_clips(db_path, job_id)

    # Any COMPLETED clip whose output file disappeared goes back to PENDING
    for c in clips:
        if c["state"] == ClipState.COMPLETED.value and c["output_path"]:
            p = Path(cast(str, c["output_path"]))
            if not (p.is_file() and p.stat().st_size == c["size_bytes"]):
                with connect(db_path) as conn:
                    conn.execute(
                        "UPDATE clips SET state = ? WHERE job_id = ? AND \"index\" = ?",
                        (ClipState.PENDING.value, job_id, c["index"]),
                    )
                c["state"] = ClipState.PENDING.value

    # Clips still PENDING need encoding; FAILED clips stay out (Phase 11 retry)
    pending = [c for c in clips if c["state"] == ClipState.PENDING.value]
    pending.sort(key=lambda c: cast(int, c["index"]))
    return job_id, pending
