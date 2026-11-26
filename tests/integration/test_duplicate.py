"""Integration tests for Phase 9 duplicate detection and locking (FR-RES-05, FR-RES-06).

Duplicate detection compares input fingerprint + output folder + config snapshot.
A second process on the same output folder fails fast via flock (RULE-26).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clipforge.manager.locks import JobLock, JobLockedError, duplicate_detected
from clipforge.storage.db import _connect
from clipforge.storage.repo import create_job
from clipforge.storage.schema import init_schema
from clipforge.utils.hashing import fingerprint


def test_job_lock_acquire_and_release(tmp_path: Path) -> None:
    """JobLock acquires on first use and releases cleanly on exit."""
    lock_dir = tmp_path / "out"
    lock_dir.mkdir(parents=True)
    with JobLock(lock_dir):
        assert (lock_dir / ".clipforge.lock").is_file()
    # After exit, another lock can be acquired immediately.
    with JobLock(lock_dir):
        pass


def test_job_lock_second_process_fails(tmp_path: Path) -> None:
    """A second JobLock on the same folder raises JobLockedError (fast fail)."""
    lock_dir = tmp_path / "out"
    lock_dir.mkdir(parents=True)
    with JobLock(lock_dir), pytest.raises(JobLockedError):
        JobLock(lock_dir).__enter__()


def test_duplicate_detects_same_input_output(tmp_path: Path) -> None:
    """duplicate_detected finds an existing job on the same input+output."""
    db_path = tmp_path / "db" / "clipforge.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    with _connect(db_path) as conn:
        init_schema(conn)

    input_file = tmp_path / "in.mp4"
    input_file.write_bytes(b"dummy video")
    job_id = create_job(db_path, input_file, out_dir, {"processing": {}, "output": {}})

    found = duplicate_detected(db_path, input_file, out_dir)
    assert found is not None
    assert found[0] == job_id


def test_duplicate_detected_none_when_no_job(tmp_path: Path) -> None:
    """duplicate_detected returns None when no job exists for input+output."""
    db_path = tmp_path / "db" / "clipforge.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    with _connect(db_path) as conn:
        init_schema(conn)

    input_file = tmp_path / "in.mp4"
    input_file.write_bytes(b"dummy video")

    assert duplicate_detected(db_path, input_file, out_dir) is None


def test_fingerprint_returns_size_and_sha(tmp_path: Path) -> None:
    """fingerprint returns size_bytes and sha256 for a file."""
    f = tmp_path / "fingerprint_me.bin"
    f.write_bytes(b"0123456789" * 1000)
    fp = fingerprint(f)
    assert fp["size_bytes"] == len(f.read_bytes())
    assert isinstance(fp["sha256"], str) and len(fp["sha256"]) == 64
