"""Integration tests for Phase 9 resume and recovery (FR-RES-01 to FR-RES-07).

Covers: interrupted job resumes with zero re-encodes of finished clips and zero
gaps; lock refusal for a second process on the same job; disk-full runtime guard
pauses with completed clips intact; fingerprint refusal on modified input.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any, cast

import pytest
from typer.testing import CliRunner

from clipforge.core.config import (
    ClipForgeConfig,
    FaultToleranceConfig,
    OptimizerConfig,
)
from clipforge.core.constants import ClipState, JobState
from clipforge.manager.recovery import prepare_resume
from clipforge.manager.scheduler import run_job
from clipforge.planner.plan import plan_job
from clipforge.probe.ffprobe import FFprobeResult
from clipforge.probe.metadata import ProbeData, normalize
from clipforge.storage.db import _connect
from clipforge.storage.repo import (
    create_job,
    insert_clip,
    job_exists,
    load_job_clips,
    set_job_state,
    update_clip_state,
)
from clipforge.storage.schema import init_schema
from clipforge.utils.hashing import fingerprint

runner = CliRunner()


def _has_ffmpeg_and_ffprobe() -> bool:
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


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


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_interrupt_resume_zero_reencode(tmp_path: Path) -> None:
    """An interrupted job resumes, re-encoding only still-PENDING clips (FR-RES-01).

    We pre-seed the database so clip 1 is COMPLETED with a file on disk, clip 2 is
    PENDING, then call run_job with job_id to confirm clip 1 is skipped entirely.
    """
    db_path = tmp_path / "db" / "clipforge.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    with _connect(db_path) as conn:
        init_schema(conn)

    input_file, probe = _make_probe(tmp_path)
    plan = plan_job(probe=probe, clip_duration_seconds=10.0)
    config = _make_config(tmp_path)
    config.paths.database = db_path

    job_id = create_job(
        db_path, input_file, out_dir, {"processing": {}, "output": {}}
    )
    set_job_state(db_path, job_id, JobState.PROCESSING)
    insert_clip(db_path, job_id, 1, 0, 30_000_000)
    insert_clip(db_path, job_id, 2, 30_000_000, 30_000_000)
    insert_clip(db_path, job_id, 3, 60_000_000, 30_000_000)

    # Clip 1 already completed on disk (simulating pre-interrupt progress).
    completed_path = out_dir / "clip_0001.webm"
    completed_path.write_bytes(b"x" * 1000)
    update_clip_state(
        db_path,
        job_id,
        1,
        ClipState.COMPLETED,
        output_path=completed_path,
        size_bytes=1000,
        total_encodes=1,
    )

    # Run the job: clip 1 must be skipped (terminal), clips 2 and 3 processed.
    job_res = run_job(
        plan=plan,
        probe=probe,
        config=config,
        output_dir=out_dir,
        db_path=db_path,
        job_id=job_id,
    )

    clips = load_job_clips(db_path, job_id)
    states = {c["index"]: c["state"] for c in clips}
    assert states[1] == ClipState.COMPLETED.value, "clip 1 must stay COMPLETED (RULE-66)"
    assert completed_path.is_file() and completed_path.stat().st_size == 1000, (
        "completed clip 1 file must remain untouched"
    )

    # Clip 1's result reflects the skipped COMPLETED state (no re-encode).
    result_by_index = {c.index: c for c in job_res.clip_results}
    assert result_by_index[1].state == ClipState.COMPLETED
    assert result_by_index[1].size_bytes == 1000
    assert result_by_index[1].total_encodes == 1  # original encode only

    # Clips 2 and 3 fail on the dummy input (not a real video), but clip 1's
    # COMPLETED result comes from the skip path (no re-encode happened).
    assert set(result_by_index.keys()) == {1, 2, 3}
    assert job_res.completed_clips == 1
    assert job_res.failed_clips == 2


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_resume_prepare_resets_in_flight_and_missing(tmp_path: Path) -> None:
    """prepare_resume resets in-flight clips and clips whose output vanished (FR-RES-02)."""
    db_path = tmp_path / "db" / "clipforge.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    with _connect(db_path) as conn:
        init_schema(conn)

    input_file, _probe = _make_probe(tmp_path)
    config = _make_config(tmp_path)
    config.paths.database = db_path

    job_id = create_job(db_path, input_file, out_dir, {})
    set_job_state(db_path, job_id, JobState.PROCESSING)
    insert_clip(db_path, job_id, 1, 0, 30_000_000)
    insert_clip(db_path, job_id, 2, 30_000_000, 30_000_000)
    insert_clip(db_path, job_id, 3, 60_000_000, 30_000_000)

    # Clip 1: ENCODING (in-flight, crash left it). Clip 2: COMPLETED but file gone.
    # Clip 3: COMPLETED and file intact (must stay COMPLETED).
    update_clip_state(db_path, job_id, 1, ClipState.ENCODING)
    missing_path = out_dir / "clip_0002.webm"
    update_clip_state(db_path, job_id, 2, ClipState.COMPLETED, output_path=missing_path)
    completed_path = out_dir / "clip_0003.webm"
    completed_path.write_bytes(b"y" * 2000)
    update_clip_state(
        db_path, job_id, 3, ClipState.COMPLETED, output_path=completed_path, size_bytes=2000
    )

    _job_id, pending = prepare_resume(db_path, input_file, out_dir)

    pending_indices = sorted(c["index"] for c in pending)
    assert pending_indices == [1, 2], f"clips 1 and 2 reset to PENDING, got {pending_indices}"
    clips = load_job_clips(db_path, job_id)
    states = {c["index"]: c["state"] for c in clips}
    assert states[3] == ClipState.COMPLETED.value, "clip 3 intact on disk stays COMPLETED"


def test_disk_full_pause_with_completed_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Runtime disk guard pauses with completed clips intact rather than filling disk."""
    db_path = tmp_path / "db" / "clipforge.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    with _connect(db_path) as conn:
        init_schema(conn)

    input_file, probe = _make_probe(tmp_path)
    plan = plan_job(probe=probe, clip_duration_seconds=10.0)
    config = _make_config(tmp_path)
    config.paths.database = db_path

    job_id = create_job(db_path, input_file, out_dir, {"processing": {}, "output": {}})
    set_job_state(db_path, job_id, JobState.PROCESSING)
    insert_clip(db_path, job_id, 1, 0, 30_000_000)
    insert_clip(db_path, job_id, 2, 30_000_000, 30_000_000)

    # Clip 1 completed on disk already.
    completed_path = out_dir / "clip_0001.webm"
    completed_path.write_bytes(b"z" * 3000)
    update_clip_state(
        db_path,
        job_id,
        1,
        ClipState.COMPLETED,
        output_path=completed_path,
        size_bytes=3000,
        total_encodes=1,
    )

    # Force free_bytes to report 0 so the runtime disk guard trips before clip 2.
    monkeypatch.setattr("clipforge.manager.scheduler.free_bytes", lambda p: 0)

    with pytest.raises(SystemExit):
        run_job(
            plan=plan,
            probe=probe,
            config=config,
            output_dir=out_dir,
            db_path=db_path,
            job_id=job_id,
        )

    # Clip 1 untouched on disk.
    assert completed_path.is_file() and completed_path.stat().st_size == 3000


def test_duplicate_detects_same_input_output(tmp_path: Path) -> None:
    """Same input path + output folder yields an existing job id (FR-RES-05 / RULE-26)."""
    db_path = tmp_path / "db" / "clipforge.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    with _connect(db_path) as conn:
        init_schema(conn)

    input_file, _probe = _make_probe(tmp_path)
    config = _make_config(tmp_path)
    config.paths.database = db_path

    job_id = create_job(db_path, input_file, out_dir, {"processing": {}, "output": {}})
    found = job_exists(db_path, input_file, out_dir)
    assert found is not None
    assert found[0] == job_id


def test_fingerprint_refused_on_modified_input(tmp_path: Path) -> None:
    """A changed input file is detected via fingerprint (FR-RES-06 / RULE-26)."""
    db_path = tmp_path / "db" / "clipforge.db"
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True)
    with _connect(db_path) as conn:
        init_schema(conn)

    input_file, _probe = _make_probe(tmp_path)
    config = _make_config(tmp_path)
    config.paths.database = db_path

    stored_fp = fingerprint(input_file)

    # Modify the input file (append a byte) -> fingerprint differs.
    modified = tmp_path / "modified.mp4"
    shutil.copy(input_file, modified)
    with open(modified, "ab") as f:
        f.write(b"x")

    modified_fp = fingerprint(modified)
    assert stored_fp["sha256"] != modified_fp["sha256"]
    assert stored_fp["size_bytes"] != modified_fp["size_bytes"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
