"""Unit tests for the in-memory scheduler (Phase 5, RULE-15, RULE-22, RULE-30)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from clipforge.core.config import ClipForgeConfig
from clipforge.core.constants import ClipState, JobState
from clipforge.encoding.runner import EncodeResult
from clipforge.encoding.verify import ClipVerification
from clipforge.manager.scheduler import run_job
from clipforge.planner.plan import JobPlan, plan_job
from clipforge.probe.ffprobe import FFprobeResult
from clipforge.probe.metadata import ProbeData, normalize


def _make_dummy_plan(tmp_path: Path, clip_count: int = 2) -> tuple[JobPlan, ProbeData]:
    input_file = tmp_path / "dummy.mp4"
    input_file.write_bytes(b"dummy")

    raw: dict[str, Any] = {
        "format": {
            "format_name": "mov,mp4",
            "format_long_name": "QuickTime / MOV",
            "start_time": "0.000000",
            "duration": str(clip_count * 10.0),
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
                "codec_long_name": "H.264",
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
    probe = normalize(FFprobeResult(streams=raw["streams"], format=raw["format"]), input_file)
    plan = plan_job(probe=probe, clip_duration_seconds=10.0)
    return plan, probe


def test_run_job_success_all_clips(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=2)
    output_dir = tmp_path / "output"
    config = ClipForgeConfig()

    def mock_run_encode(
        cmd: list[str], output_part_path: Path, **kwargs: Any
    ) -> EncodeResult:
        output_part_path.write_bytes(b"dummy-webm-bytes")
        return EncodeResult(
            success=True,
            exit_code=0,
            output_path=output_part_path,
            size_bytes=len(b"dummy-webm-bytes"),
            duration_seconds=10.0,
            is_timeout=False,
            stderr_tail="",
        )

    def mock_verify_clip(clip_path: Path, **kwargs: Any) -> ClipVerification:
        return ClipVerification(
            path=clip_path,
            valid=True,
            size_bytes=100,
            is_oversize=False,
            format_name="webm",
            video_codec="vp9",
            audio_codec="opus",
            duration_seconds=10.0,
            errors=[],
        )

    with (
        patch("clipforge.manager.scheduler.run_encode", side_effect=mock_run_encode),
        patch("clipforge.manager.scheduler.verify_clip", side_effect=mock_verify_clip),
    ):
        result = run_job(plan, probe, config, output_dir)

    assert result.state == JobState.COMPLETED
    assert result.completed_clips == 2
    assert result.failed_clips == 0
    assert len(result.clip_results) == 2

    # Verify 4-digit padding and naming
    clip1 = output_dir / "clip_0001.webm"
    clip2 = output_dir / "clip_0002.webm"
    assert clip1.exists()
    assert clip2.exists()
    assert not (output_dir / ".clipforge_tmp").exists()


def test_run_job_oversize_retry_and_exhaustion(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=1)
    output_dir = tmp_path / "output_oversize"
    config = ClipForgeConfig()

    # Always oversize
    def mock_run_encode(
        cmd: list[str], output_part_path: Path, **kwargs: Any
    ) -> EncodeResult:
        output_part_path.write_bytes(b"x" * 5_000_000)
        return EncodeResult(
            success=True,
            exit_code=0,
            output_path=output_part_path,
            size_bytes=5_000_000,
            duration_seconds=10.0,
            is_timeout=False,
            stderr_tail="",
        )

    with patch("clipforge.manager.scheduler.run_encode", side_effect=mock_run_encode):
        result = run_job(plan, probe, config, output_dir)

    assert result.state == JobState.FAILED
    assert result.completed_clips == 0
    assert result.failed_clips == 1

    clip_res = result.clip_results[0]
    assert clip_res.state == ClipState.FAILED_SIZE
    assert clip_res.size_attempts == config.optimizer.size_attempts
    # No oversize file published
    assert not (output_dir / "clip_0001.webm").exists()


def test_run_job_keyboard_interrupt_cleanup(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=2)
    output_dir = tmp_path / "output_interrupt"
    config = ClipForgeConfig()

    def mock_run_encode(
        cmd: list[str], output_part_path: Path, **kwargs: Any
    ) -> EncodeResult:
        output_part_path.write_bytes(b"partial-data")
        raise KeyboardInterrupt()

    with patch("clipforge.manager.scheduler.run_encode", side_effect=mock_run_encode):
        result = run_job(plan, probe, config, output_dir)

    assert result.state == JobState.INTERRUPTED
    assert result.completed_clips == 0
    # Cleaned up orphan .part
    assert not (output_dir / ".clipforge_tmp" / "clip_0001.webm.part").exists()
