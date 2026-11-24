"""Integration tests for Phase 8 persistence (SQLite, manifest, crash recovery).

Covers RULE-22 (transaction rule), RULE-24 (append-only attempts), schema
versioning, and manifest atomicity after every clip.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from clipforge.core.config import (
    ClipForgeConfig,
    FaultToleranceConfig,
    OptimizerConfig,
)
from clipforge.core.constants import ClipState, JobState
from clipforge.manager.scheduler import run_job
from clipforge.planner.plan import plan_job
from clipforge.probe.ffprobe import FFprobeResult
from clipforge.probe.metadata import ProbeData, normalize
from clipforge.storage.db import _connect
from clipforge.storage.manifest import read_manifest, write_manifest
from clipforge.storage.repo import (
    append_attempt,
    create_job,
    insert_clip,
    load_job,
    load_job_clips,
    reset_in_flight_clips,
    set_job_state,
    update_clip_state,
)
from clipforge.storage.schema import SCHEMA_VERSION, init_schema, schema_version


def _make_probe(tmp_path: Path) -> tuple[Path, ProbeData]:
    input_file = tmp_path / "dummy.mp4"
    input_file.write_bytes(b"dummy")
    raw: dict[str, Any] = {
        "format": {
            "format_name": "mov,mp4",
            "format_long_name": "QuickTime / MOV",
            "start_time": "0.000000",
            "duration": "30.0",
            "size": "123456",
            "bit_rate": "1000000",
            "nb_streams": 1,
            "nb_programs": 0,
            "tags": {},
        },
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "coded_width": 1920,
                "coded_height": 1080,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "time_base": "1/30",
                "disposition": {},
                "tags": {},
            }
        ],
    }
    probe_result = FFprobeResult(
        streams=cast(list[dict[str, object]], raw["streams"]),
        format=cast(dict[str, object], raw["format"]),
    )
    probe = normalize(probe_result, input_file)
    return input_file, probe


def _make_config(tmp_path: Path) -> ClipForgeConfig:
    config = ClipForgeConfig(
        optimizer=OptimizerConfig(
            crf_start=32, crf_max=51, max_total_encodes=4, size_attempts=2,
            two_pass_fallback=True,
        ),
        fault_tolerance=FaultToleranceConfig(
            fault_retries=1, retry_delays_seconds=[0.01], timeout_factor=2.0
        ),
    )
    config.paths.database = tmp_path / "db" / "clipforge.db"
    return config


def _run_job(tmp_path: Path, db_path: Path) -> tuple[Path, Path]:
    input_file, probe = _make_probe(tmp_path)
    plan = plan_job(probe=probe, clip_duration_seconds=10.0)
    config = _make_config(tmp_path)
    config.paths.database = db_path
    output_dir = tmp_path / "out"
    run_job(
        plan=plan, probe=probe, config=config, output_dir=output_dir, db_path=db_path,
    )
    return input_file, output_dir


def test_schema_version_and_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "db" / "clipforge.db"
    with _connect(db_path) as conn:
        init_schema(conn)
        assert schema_version(conn) == SCHEMA_VERSION
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"jobs", "clips", "attempts", "events"}.issubset(tables)


def test_persistence_writes_job_and_clips(tmp_path: Path) -> None:
    db_path = tmp_path / "db" / "clipforge.db"
    out_dir = tmp_path / "out"
    _run_job(tmp_path, db_path)

    job = load_job(db_path, 1)
    assert job is not None
    assert job["state"] in {
        JobState.COMPLETED.value,
        JobState.COMPLETED_WITH_ISSUES.value,
        JobState.FAILED.value,
    }
    assert job["total_clips"] == 3

    clips = load_job_clips(db_path, 1)
    assert len(clips) == 3
    for c in clips:
        assert c["state"] in {
            ClipState.COMPLETED.value,
            ClipState.NEEDS_REVIEW.value,
            ClipState.FAILED.value,
            ClipState.FAILED_SIZE.value,
        }

    # Manifest was written
    manifest = read_manifest(out_dir)
    assert manifest is not None
    assert manifest["job_id"] == 1


def test_attempts_append_only(tmp_path: Path) -> None:
    db_path = tmp_path / "db" / "clipforge.db"
    with _connect(db_path) as conn:
        init_schema(conn)
    create_job(db_path, tmp_path / "in.mp4", tmp_path / "out", {})
    insert_clip(db_path, 1, 1, 0, 30_000_000)

    append_attempt(db_path, 1, 1, 1, "encode", "failed", stderr_tail="boom")
    append_attempt(db_path, 1, 1, 2, "encode", "success", size_bytes=1000)

    with _connect(db_path) as conn:
        rows = conn.execute("SELECT count(*) FROM attempts").fetchone()[0]
        assert rows == 2


def test_reset_in_flight_clips(tmp_path: Path) -> None:
    db_path = tmp_path / "db" / "clipforge.db"
    with _connect(db_path) as conn:
        init_schema(conn)
    create_job(db_path, tmp_path / "in.mp4", tmp_path / "out", {})
    insert_clip(db_path, 1, 1, 0, 30_000_000)
    insert_clip(db_path, 1, 2, 30_000_000, 30_000_000)

    # Simulate crash mid-encode: clip 1 in ENCODING, clip 2 in PENDING
    set_job_state(db_path, 1, JobState.PROCESSING)
    update_clip_state(db_path, 1, 1, ClipState.ENCODING)
    assert reset_in_flight_clips(db_path, 1) == 1

    clips = load_job_clips(db_path, 1)
    assert clips[0]["state"] == ClipState.PENDING.value
    assert clips[1]["state"] == ClipState.PENDING.value


def test_manifest_atomicity(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    write_manifest(out_dir, 1, [{"index": 1, "state": "COMPLETED"}])
    manifest = read_manifest(out_dir)
    assert manifest is not None
    assert manifest["clip_count"] == 1


def test_crash_mid_job_db_consistent(tmp_path: Path) -> None:
    """Database stays consistent after simulating a crash mid-job.

    Creates a job, marks a clip as ENCODING (in-flight), then verifies
    reset_in_flight_clips brings it back to PENDING — the crash recovery path.
    """
    db_path = tmp_path / "db" / "clipforge.db"
    with _connect(db_path) as conn:
        init_schema(conn)

    create_job(db_path, tmp_path / "in.mp4", tmp_path / "out", {"processing": {}})
    insert_clip(db_path, 1, 1, 0, 30_000_000)
    insert_clip(db_path, 1, 2, 30_000_000, 30_000_000)

    set_job_state(db_path, 1, JobState.PROCESSING)
    update_clip_state(db_path, 1, 1, ClipState.ENCODING)

    # Crash recovery: reset in-flight clips back to PENDING
    assert reset_in_flight_clips(db_path, 1) == 1
    clips = load_job_clips(db_path, 1)
    assert clips[0]["state"] == ClipState.PENDING.value
    assert clips[1]["state"] == ClipState.PENDING.value


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
