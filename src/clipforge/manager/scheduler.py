"""In-memory job scheduler and execution loop (Phase 5, FR-ENC-05, FR-ENC-07, RULE-30)."""

from __future__ import annotations

import contextlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from clipforge.core.config import ClipForgeConfig
from clipforge.core.constants import (
    TARGET_CLIP_SIZE_BYTES,
    ClipState,
    JobState,
)
from clipforge.encoding.builder import build_clip_command
from clipforge.encoding.progress import ProgressFrame
from clipforge.encoding.runner import run_encode
from clipforge.encoding.verify import verify_clip
from clipforge.optimizer.budget import (
    calculate_budget,
    default_audio_bitrate_bps,
)
from clipforge.optimizer.size_loop import (
    adjust_crf_for_underuse,
    can_retry_size,
    check_underuse,
    is_oversize,
    recalculate_bitrate,
    should_promote_two_pass,
)
from clipforge.planner.plan import JobPlan
from clipforge.probe.metadata import ProbeData
from clipforge.utils.atomic import atomic_publish


def _clean_passlogs(tmp_dir: Path, clip_filename: str) -> None:
    """Remove any temporary two-pass analysis log files."""
    for p in tmp_dir.glob(f"{clip_filename}_passlog*"):
        with contextlib.suppress(OSError):
            p.unlink(missing_ok=True)


@dataclass(frozen=True)
class ClipResult:
    """Outcome of processing an individual clip."""

    index: int
    start_us: int
    duration_us: int
    state: ClipState
    output_path: Path | None
    size_bytes: int
    size_attempts: int
    fault_retries: int
    total_encodes: int
    two_pass: bool = False
    crf: int = 32
    error_message: str | None = None


@dataclass(frozen=True)
class JobResult:
    """Outcome of processing the complete job."""

    input_path: Path
    output_dir: Path
    state: JobState
    clip_results: list[ClipResult]
    total_clips: int
    completed_clips: int
    failed_clips: int
    review_clips: int


def run_job(
    plan: JobPlan,
    probe: ProbeData,
    config: ClipForgeConfig,
    output_dir: Path,
    on_clip_start: Callable[[int, int], None] | None = None,
    on_clip_progress: Callable[[int, ProgressFrame], None] | None = None,
    on_clip_done: Callable[[ClipResult], None] | None = None,
) -> JobResult:
    """Execute the full job sequentially in-memory without database persistence.

    Args:
        plan: Prepared job boundaries and feasibility plan.
        probe: Source media probe data.
        config: Effective configuration for encoding, limits, and retries.
        output_dir: Directory where final clips and temporary parts will live.
        on_clip_start: Optional callback when a clip starts (idx_1_based, total).
        on_clip_progress: Optional callback invoked on FFmpeg progress frames.
        on_clip_done: Optional callback invoked when a clip finishes.

    Returns:
        JobResult summarizing the outcome of all clips.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_dir / ".clipforge_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    clip_results: list[ClipResult] = []
    padding = max(4, len(str(plan.clip_count)))
    job_state = JobState.PROCESSING
    part_path: Path | None = None

    try:
        for boundary in plan.boundaries:
            clip_idx = boundary.index + 1
            if on_clip_start:
                on_clip_start(clip_idx, plan.clip_count)

            clip_filename = f"clip_{clip_idx:0{padding}d}.webm"
            part_path = tmp_dir / f"{clip_filename}.part"
            final_path = output_dir / clip_filename
            passlog_prefix = tmp_dir / f"{clip_filename}_passlog"

            # Calculate initial budget and starting CRF (FR-OPT-02, 03, 05)
            audio_ch = (
                probe.primary_audio.channels
                if (probe.primary_audio and probe.primary_audio.channels is not None)
                else 0
            )
            if config.output.audio_channels == "stereo" and audio_ch > 2:
                audio_ch = 2
            audio_bps = default_audio_bitrate_bps(audio_ch) if probe.has_audio else 0

            v = probe.primary_video
            height = v.display_height if (v and v.display_height) else (v.height if v else 1080)
            feasibility_verdict = plan.feasibility.verdict if plan.feasibility else "comfortable"

            budget = calculate_budget(
                duration_us=boundary.duration_us,
                audio_bps=audio_bps,
                target_bytes=TARGET_CLIP_SIZE_BYTES,
                height=height,
                feasibility_class=feasibility_verdict,
                crf_start=config.optimizer.crf_start,
                crf_max=config.optimizer.crf_max,
            )
            current_video_bps = budget.video_bps
            current_audio_bps = budget.audio_bps
            current_crf = budget.crf
            clip_duration_sec = boundary.duration_us / 1_000_000

            size_attempts = 0
            fault_retries = 0
            total_encodes = 0
            underuse_attempts = 0
            is_two_pass = False
            clip_state = ClipState.PENDING
            error_msg: str | None = None
            final_size = 0

            while True:
                if total_encodes >= config.optimizer.max_total_encodes:
                    clip_state = ClipState.FAILED_LIMIT
                    error_msg = (
                        f"exceeded maximum total encodes ({config.optimizer.max_total_encodes})"
                    )
                    part_path.unlink(missing_ok=True)
                    _clean_passlogs(tmp_dir, clip_filename)
                    break

                timeout = max(60.0, clip_duration_sec * config.fault_tolerance.timeout_factor)

                def _progress_cb(frame: ProgressFrame, bound_idx: int = clip_idx) -> None:
                    if on_clip_progress:
                        on_clip_progress(bound_idx, frame)

                if is_two_pass:
                    # Pass 1: Analysis pass
                    pass1_cmd = build_clip_command(
                        probe=probe,
                        start_us=boundary.start_us,
                        duration_us=boundary.duration_us,
                        video_bps=current_video_bps,
                        output_part_path=part_path,
                        audio_bps=current_audio_bps,
                        profile=config.output.profile,
                        crf=current_crf,
                        threads=config.performance.ffmpeg_threads,
                        audio_channels_policy=config.output.audio_channels,
                        pass_number=1,
                        passlogfile=passlog_prefix,
                    )
                    total_encodes += 1
                    pass1_res = run_encode(
                        cmd=pass1_cmd,
                        output_part_path=part_path,
                        clip_duration_seconds=clip_duration_sec,
                        timeout=timeout,
                        on_progress=_progress_cb,
                        is_analysis_pass=True,
                    )
                    if not pass1_res.success:
                        _clean_passlogs(tmp_dir, clip_filename)
                        if (
                            fault_retries < config.fault_tolerance.fault_retries
                            and total_encodes < config.optimizer.max_total_encodes
                        ):
                            fault_retries += 1
                            delays = config.fault_tolerance.retry_delays_seconds
                            delay = (
                                delays[min(fault_retries - 1, len(delays) - 1)] if delays else 0.0
                            )
                            if delay > 0:
                                time.sleep(delay)
                            continue

                        clip_state = ClipState.FAILED
                        tail_err = pass1_res.stderr_tail or f"exit code {pass1_res.exit_code}"
                        error_msg = f"two-pass analysis failed: {tail_err}"
                        part_path.unlink(missing_ok=True)
                        break

                    # Check limit before pass 2
                    if total_encodes >= config.optimizer.max_total_encodes:
                        _clean_passlogs(tmp_dir, clip_filename)
                        clip_state = ClipState.FAILED_LIMIT
                        error_msg = (
                            f"exceeded maximum total encodes ({config.optimizer.max_total_encodes})"
                        )
                        part_path.unlink(missing_ok=True)
                        break

                    # Pass 2: Final encode
                    cmd = build_clip_command(
                        probe=probe,
                        start_us=boundary.start_us,
                        duration_us=boundary.duration_us,
                        video_bps=current_video_bps,
                        output_part_path=part_path,
                        audio_bps=current_audio_bps,
                        profile=config.output.profile,
                        crf=current_crf,
                        threads=config.performance.ffmpeg_threads,
                        audio_channels_policy=config.output.audio_channels,
                        pass_number=2,
                        passlogfile=passlog_prefix,
                    )
                else:
                    cmd = build_clip_command(
                        probe=probe,
                        start_us=boundary.start_us,
                        duration_us=boundary.duration_us,
                        video_bps=current_video_bps,
                        output_part_path=part_path,
                        audio_bps=current_audio_bps,
                        profile=config.output.profile,
                        crf=current_crf,
                        threads=config.performance.ffmpeg_threads,
                        audio_channels_policy=config.output.audio_channels,
                    )

                total_encodes += 1
                encode_res = run_encode(
                    cmd=cmd,
                    output_part_path=part_path,
                    clip_duration_seconds=clip_duration_sec,
                    timeout=timeout,
                    on_progress=_progress_cb,
                )
                if is_two_pass:
                    _clean_passlogs(tmp_dir, clip_filename)

                if not encode_res.success:
                    if (
                        fault_retries < config.fault_tolerance.fault_retries
                        and total_encodes < config.optimizer.max_total_encodes
                    ):
                        fault_retries += 1
                        delays = config.fault_tolerance.retry_delays_seconds
                        delay = delays[min(fault_retries - 1, len(delays) - 1)] if delays else 0.0
                        if delay > 0:
                            time.sleep(delay)
                        continue

                    clip_state = ClipState.FAILED
                    tail_err = encode_res.stderr_tail or f"exit code {encode_res.exit_code}"
                    error_msg = f"encode failed: {tail_err}"
                    part_path.unlink(missing_ok=True)
                    break

                # RULE-08, RULE-22: verify size before rename, never after
                actual_size = (
                    part_path.stat().st_size if part_path.exists() else encode_res.size_bytes
                )
                if is_oversize(actual_size, config.output.max_size):
                    size_attempts += 1
                    is_two_pass = should_promote_two_pass(
                        size_attempts, config.optimizer.two_pass_fallback
                    )
                    if can_retry_size(
                        size_attempts,
                        total_encodes,
                        config.optimizer.size_attempts,
                        config.optimizer.max_total_encodes,
                    ):
                        current_video_bps = recalculate_bitrate(
                            current_video_bps, actual_size, TARGET_CLIP_SIZE_BYTES
                        )
                        part_path.unlink(missing_ok=True)
                        continue

                    clip_state = ClipState.FAILED_SIZE
                    error_msg = (
                        f"size {actual_size:,} bytes exceeds hard limit "
                        f"{config.output.max_size:,} after {size_attempts} size attempts"
                    )
                    part_path.unlink(missing_ok=True)
                    break

                # Under-use check hook (FR-OPT-11, paired with quality gates in Phase 7)
                quality_passed = True  # Tier 1/2 gates arrive in Phase 7
                if check_underuse(
                    actual_size_bytes=actual_size,
                    target_size_bytes=TARGET_CLIP_SIZE_BYTES,
                    quality_passed=quality_passed,
                    underuse_attempts=underuse_attempts,
                ):
                    underuse_attempts += 1
                    current_crf = adjust_crf_for_underuse(current_crf)
                    part_path.unlink(missing_ok=True)
                    continue

                # Container and codec validation
                verification = verify_clip(
                    clip_path=part_path,
                    max_size_bytes=config.output.max_size,
                    expected_duration=clip_duration_sec,
                )
                if not verification.valid:
                    if (
                        fault_retries < config.fault_tolerance.fault_retries
                        and total_encodes < config.optimizer.max_total_encodes
                    ):
                        fault_retries += 1
                        part_path.unlink(missing_ok=True)
                        continue

                    clip_state = ClipState.FAILED
                    error_msg = f"clip verification failed: {'; '.join(verification.errors)}"
                    part_path.unlink(missing_ok=True)
                    break

                # Atomic publish (RULE-08, fsync + os.replace)
                atomic_publish(part_path, final_path)
                clip_state = ClipState.COMPLETED
                final_size = actual_size
                break

            result = ClipResult(
                index=clip_idx,
                start_us=boundary.start_us,
                duration_us=boundary.duration_us,
                state=clip_state,
                output_path=final_path if clip_state == ClipState.COMPLETED else None,
                size_bytes=final_size,
                size_attempts=size_attempts,
                fault_retries=fault_retries,
                total_encodes=total_encodes,
                two_pass=is_two_pass,
                crf=current_crf,
                error_message=error_msg,
            )
            clip_results.append(result)
            if on_clip_done:
                on_clip_done(result)

    except KeyboardInterrupt:
        if part_path and part_path.exists():
            part_path.unlink(missing_ok=True)
        if tmp_dir.exists():
            for p in tmp_dir.glob("*.part"):
                p.unlink(missing_ok=True)
            for p in tmp_dir.glob("*_passlog*"):
                p.unlink(missing_ok=True)
        job_state = JobState.INTERRUPTED

    # Remove temporary directory if empty
    try:
        if tmp_dir.exists() and not any(tmp_dir.iterdir()):
            tmp_dir.rmdir()
    except OSError:
        pass

    completed = sum(1 for c in clip_results if c.state == ClipState.COMPLETED)
    failed = sum(
        1
        for c in clip_results
        if c.state in (ClipState.FAILED, ClipState.FAILED_SIZE, ClipState.FAILED_LIMIT)
    )
    review = sum(1 for c in clip_results if c.state == ClipState.NEEDS_REVIEW)

    if job_state != JobState.INTERRUPTED:
        if failed > 0 or review > 0:
            job_state = JobState.COMPLETED_WITH_ISSUES if completed > 0 else JobState.FAILED
        else:
            job_state = JobState.COMPLETED

    return JobResult(
        input_path=plan.input_path,
        output_dir=output_dir,
        state=job_state,
        clip_results=clip_results,
        total_clips=plan.clip_count,
        completed_clips=completed,
        failed_clips=failed,
        review_clips=review,
    )
