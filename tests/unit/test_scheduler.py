"""Unit tests for the in-memory scheduler (Phase 5, RULE-15, RULE-22, RULE-30)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

from clipforge.core.config import ClipForgeConfig, FaultToleranceConfig, OptimizerConfig
from clipforge.core.constants import ClipState, JobState
from clipforge.encoding.runner import EncodeResult
from clipforge.encoding.verify import ClipVerification
from clipforge.manager.scheduler import run_job
from clipforge.optimizer.quality import QualityVerdict
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

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
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
        patch(
            "clipforge.manager.scheduler.check_quality_gate",
            return_value=QualityVerdict(
                passed=True, metric="ssim", score=0.98, threshold=0.95, sampled=True
            ),
        ),
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
    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
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
    # Consumed 6 total encodes (1-pass, 1-pass, two-pass [2 runs], two-pass [2 runs])
    assert clip_res.total_encodes == 6
    assert clip_res.two_pass is True
    # No oversize file published
    assert not (output_dir / "clip_0001.webm").exists()


def test_run_job_two_pass_promotion_and_success(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=1)
    output_dir = tmp_path / "output_twopass_success"
    config = ClipForgeConfig()

    calls: list[list[str]] = []

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
        calls.append(cmd)
        # Create a dummy passlog file during pass 1 if passlogfile is specified
        if "-passlogfile" in cmd:
            log_idx = cmd.index("-passlogfile") + 1
            log_file = Path(f"{cmd[log_idx]}-0.log")
            log_file.write_text("dummy-passlog")

        # First 2 attempts: 1-pass oversize (5 MB)
        # 3rd attempt: pass 1 analysis (size 0)
        # 4th attempt: pass 2 encode (3 MB, within limit)
        if kwargs.get("is_analysis_pass"):
            return EncodeResult(
                success=True,
                exit_code=0,
                output_path=output_part_path,
                size_bytes=0,
                duration_seconds=10.0,
                is_timeout=False,
                stderr_tail="",
            )

        size = 5_000_000 if len(calls) <= 2 else 3_000_000
        output_part_path.write_bytes(b"x" * size)
        return EncodeResult(
            success=True,
            exit_code=0,
            output_path=output_part_path,
            size_bytes=size,
            duration_seconds=10.0,
            is_timeout=False,
            stderr_tail="",
        )

    def mock_verify_clip(clip_path: Path, **kwargs: Any) -> ClipVerification:
        return ClipVerification(
            path=clip_path,
            valid=True,
            size_bytes=clip_path.stat().st_size,
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
        patch(
            "clipforge.manager.scheduler.check_quality_gate",
            return_value=QualityVerdict(
                passed=True, metric="ssim", score=0.98, threshold=0.95, sampled=True
            ),
        ),
    ):
        result = run_job(plan, probe, config, output_dir)

    assert result.state == JobState.COMPLETED
    assert result.completed_clips == 1
    clip_res = result.clip_results[0]
    assert clip_res.state == ClipState.COMPLETED
    assert clip_res.two_pass is True
    assert clip_res.size_attempts == 2
    assert clip_res.total_encodes == 4  # 1-pass + 1-pass + pass1 + pass2
    assert clip_res.size_bytes == 3_000_000

    # Verify pass flags in calls
    assert "-pass" not in calls[0]
    assert "-pass" not in calls[1]
    assert calls[2][calls[2].index("-pass") + 1] == "1"
    assert calls[3][calls[3].index("-pass") + 1] == "2"

    # Verify passlogs were cleaned up (no leftover log files in tmp)
    assert not any(output_dir.glob(".clipforge_tmp/*_passlog*"))
    assert (output_dir / "clip_0001.webm").exists()


def test_run_job_max_total_encodes_exhaustion(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=1)
    output_dir = tmp_path / "output_limit_exhaust"
    # Set max_total_encodes to 3
    config = ClipForgeConfig(optimizer=OptimizerConfig(max_total_encodes=3, size_attempts=4))

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
        # Always oversize
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
    clip_res = result.clip_results[0]
    assert clip_res.state == ClipState.FAILED_LIMIT
    assert clip_res.total_encodes == 3
    assert "exceeded maximum total encodes" in (clip_res.error_message or "")


def test_run_job_starting_crf_applied(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=1)
    output_dir = tmp_path / "output_crf"
    config = ClipForgeConfig(optimizer=OptimizerConfig(crf_start=25, crf_max=40))

    observed_crf: list[str] = []

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
        crf_val = cmd[cmd.index("-crf") + 1]
        observed_crf.append(crf_val)
        output_part_path.write_bytes(b"x" * 100)
        return EncodeResult(
            success=True,
            exit_code=0,
            output_path=output_part_path,
            size_bytes=100,
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
        patch(
            "clipforge.manager.scheduler.check_quality_gate",
            return_value=QualityVerdict(
                passed=True, metric="ssim", score=0.98, threshold=0.95, sampled=True
            ),
        ),
    ):
        result = run_job(plan, probe, config, output_dir)

    assert result.state == JobState.COMPLETED
    assert observed_crf == ["25"]
    assert result.clip_results[0].crf == 25


def test_run_job_keyboard_interrupt_cleanup(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=2)
    output_dir = tmp_path / "output_interrupt"
    config = ClipForgeConfig()

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
        output_part_path.write_bytes(b"partial-data")
        raise KeyboardInterrupt()

    with patch("clipforge.manager.scheduler.run_encode", side_effect=mock_run_encode):
        result = run_job(plan, probe, config, output_dir)

    assert result.state == JobState.INTERRUPTED
    assert result.completed_clips == 0
    # Cleaned up orphan .part
    assert not (output_dir / ".clipforge_tmp" / "clip_0001.webm.part").exists()


def test_run_job_quality_gate_failure_needs_review(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=1)
    output_dir = tmp_path / "output_quality_fail"
    config = ClipForgeConfig()

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
        # Size near target (3.5 MB) so underuse does not trigger (> 75% of target)
        size = 3_500_000
        output_part_path.write_bytes(b"x" * size)
        return EncodeResult(
            success=True,
            exit_code=0,
            output_path=output_part_path,
            size_bytes=size,
            duration_seconds=10.0,
            is_timeout=False,
            stderr_tail="",
        )

    def mock_verify_clip(clip_path: Path, **kwargs: Any) -> ClipVerification:
        return ClipVerification(
            path=clip_path,
            valid=True,
            size_bytes=clip_path.stat().st_size,
            is_oversize=False,
            format_name="webm",
            video_codec="vp9",
            audio_codec="opus",
            duration_seconds=10.0,
            errors=[],
        )

    failing_verdict = QualityVerdict(
        passed=False,
        metric="ssim",
        score=0.91,
        threshold=0.95,
        sampled=True,
    )

    with (
        patch("clipforge.manager.scheduler.run_encode", side_effect=mock_run_encode),
        patch("clipforge.manager.scheduler.verify_clip", side_effect=mock_verify_clip),
        patch("clipforge.manager.scheduler.check_quality_gate", return_value=failing_verdict),
    ):
        result = run_job(plan, probe, config, output_dir)

    # RULE-45, RULE-74: File kept on disk, marked NEEDS_REVIEW, excluded from completed_clips
    assert result.state == JobState.COMPLETED_WITH_ISSUES
    assert result.completed_clips == 0
    assert result.review_clips == 1
    assert result.failed_clips == 0

    clip_res = result.clip_results[0]
    assert clip_res.state == ClipState.NEEDS_REVIEW
    assert clip_res.quality_metric == "ssim"
    assert clip_res.quality_score == 0.91
    assert clip_res.quality_threshold == 0.95
    assert (output_dir / "clip_0001.webm").exists()


def test_run_job_quality_gate_underuse_retry(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=1)
    output_dir = tmp_path / "output_underuse"
    config = ClipForgeConfig()

    observed_crfs: list[int] = []

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
        crf_val = int(cmd[cmd.index("-crf") + 1])
        observed_crfs.append(crf_val)
        # Size < 75% of target (2.0 MB < 2.98 MB)
        size = 2_000_000
        output_part_path.write_bytes(b"x" * size)
        return EncodeResult(
            success=True,
            exit_code=0,
            output_path=output_part_path,
            size_bytes=size,
            duration_seconds=10.0,
            is_timeout=False,
            stderr_tail="",
        )

    def mock_verify_clip(clip_path: Path, **kwargs: Any) -> ClipVerification:
        return ClipVerification(
            path=clip_path,
            valid=True,
            size_bytes=clip_path.stat().st_size,
            is_oversize=False,
            format_name="webm",
            video_codec="vp9",
            audio_codec="opus",
            duration_seconds=10.0,
            errors=[],
        )

    # First attempt fails gate; second attempt passes gate
    verdicts = [
        QualityVerdict(passed=False, metric="ssim", score=0.92, threshold=0.95, sampled=True),
        QualityVerdict(passed=True, metric="ssim", score=0.97, threshold=0.95, sampled=True),
    ]

    with (
        patch("clipforge.manager.scheduler.run_encode", side_effect=mock_run_encode),
        patch("clipforge.manager.scheduler.verify_clip", side_effect=mock_verify_clip),
        patch("clipforge.manager.scheduler.check_quality_gate", side_effect=verdicts),
    ):
        result = run_job(plan, probe, config, output_dir)

    # FR-OPT-11: Underuse earned one retry at crf - 4
    assert len(observed_crfs) == 2
    assert observed_crfs[1] == observed_crfs[0] - 4
    assert result.state == JobState.COMPLETED
    assert result.completed_clips == 1
    assert result.clip_results[0].state == ClipState.COMPLETED


def test_run_job_timing_mismatch_retry_and_needs_review(tmp_path: Path) -> None:
    plan, probe = _make_dummy_plan(tmp_path, clip_count=1)
    output_dir = tmp_path / "output_timing_mismatch"
    config = ClipForgeConfig(
        fault_tolerance=FaultToleranceConfig(retry_delays_seconds=[0.0, 0.0, 0.0])
    )

    encode_calls = 0

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
        nonlocal encode_calls
        encode_calls += 1
        output_part_path.write_bytes(b"dummy")
        return EncodeResult(
            success=True,
            exit_code=0,
            output_path=output_part_path,
            size_bytes=100,
            duration_seconds=8.0,
            is_timeout=False,
            stderr_tail="",
        )

    def mock_verify_clip(clip_path: Path, **kwargs: Any) -> ClipVerification:
        return ClipVerification(
            path=clip_path,
            valid=False,
            size_bytes=100,
            is_oversize=False,
            format_name="webm",
            video_codec="vp9",
            audio_codec="opus",
            duration_seconds=8.0,
            errors=["duration diverges > 1 frame"],
            timing_mismatch=True,
        )

    with (
        patch("clipforge.manager.scheduler.run_encode", side_effect=mock_run_encode),
        patch("clipforge.manager.scheduler.verify_clip", side_effect=mock_verify_clip),
    ):
        result = run_job(plan, probe, config, output_dir)

    # FR-SPL-08: Timing mismatch retries as transient fault, then marks NEEDS_REVIEW
    assert encode_calls == config.fault_tolerance.fault_retries + 1
    assert result.state == JobState.COMPLETED_WITH_ISSUES
    assert result.review_clips == 1
    assert result.completed_clips == 0
    assert (output_dir / "clip_0001.webm").exists()


def test_run_job_degradation_ladder_fps(tmp_path: Path) -> None:
    input_file = tmp_path / "dummy60.mp4"
    input_file.write_bytes(b"dummy")

    raw: dict[str, Any] = {
        "format": {"format_name": "mov,mp4", "duration": "10.0", "size": "12345"},
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "60/1",
                "avg_frame_rate": "60/1",
                "time_base": "1/60",
                "disposition": {},
                "tags": {},
            }
        ],
    }
    probe = normalize(FFprobeResult(streams=raw["streams"], format=raw["format"]), input_file)
    plan = plan_job(probe=probe, clip_duration_seconds=10.0)
    output_dir = tmp_path / "output_ladder_fps"

    from clipforge.core.config import OutputConfig

    config = ClipForgeConfig(output=OutputConfig(on_oversize="fps"))

    observed_cmds: list[list[str]] = []

    def mock_run_encode(cmd: list[str], output_part_path: Path, **kwargs: Any) -> EncodeResult:
        observed_cmds.append(cmd)
        # Check if FPS filter is applied (halved to 30 fps)
        has_fps = any("fps=30" in arg for arg in cmd)
        size = 3_000_000 if has_fps else 5_000_000
        output_part_path.write_bytes(b"x" * size)
        return EncodeResult(
            success=True,
            exit_code=0,
            output_path=output_part_path,
            size_bytes=size,
            duration_seconds=10.0,
            is_timeout=False,
            stderr_tail="",
        )

    def mock_verify_clip(clip_path: Path, **kwargs: Any) -> ClipVerification:
        return ClipVerification(
            path=clip_path,
            valid=True,
            size_bytes=clip_path.stat().st_size,
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
        patch(
            "clipforge.manager.scheduler.check_quality_gate",
            return_value=QualityVerdict(
                passed=True, metric="ssim", score=0.98, threshold=0.95, sampled=True
            ),
        ),
    ):
        result = run_job(plan, probe, config, output_dir)

    assert result.state == JobState.COMPLETED
    assert result.completed_clips == 1
    clip_res = result.clip_results[0]
    assert "fps_30.0" in clip_res.degradation
    assert (output_dir / "clip_0001.webm").exists()
