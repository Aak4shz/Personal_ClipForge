"""Database-backed job scheduler and execution loop.

Phase 5 / Phase 8; FR-ENC-05, FR-ENC-07, RULE-22, RULE-30.

Every clip state change commits to SQLite before the corresponding filesystem
mutation happens (the transaction rule).
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

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
from clipforge.optimizer.ladder import (
    DegradationState,
    next_degradation_step,
)
from clipforge.optimizer.quality import (
    QualityVerdict,
    check_quality_gate,
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
from clipforge.storage.manifest import write_manifest
from clipforge.storage.repo import (
    append_attempt,
    create_job,
    insert_clip,
    set_job_counts,
    set_job_state,
    update_clip_state,
)
from clipforge.storage.schema import init_schema
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
    degradation: tuple[str, ...] = ()
    quality_metric: str | None = None
    quality_score: float | None = None
    quality_threshold: float | None = None


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
    db_path: Path | None = None,
    job_id: int | None = None,
    on_clip_start: Callable[[int, int], None] | None = None,
    on_clip_progress: Callable[[int, ProgressFrame], None] | None = None,
    on_clip_done: Callable[[ClipResult], None] | None = None,
) -> JobResult:
    """Execute the full job sequentially with SQLite persistence (RULE-22).

    Every clip state change commits to SQLite before the corresponding
    filesystem mutation. A job killed at any moment leaves a database that
    opens consistently and describes exactly what finished.

    Args:
        plan: Prepared job boundaries and feasibility plan.
        probe: Source media probe data.
        config: Effective configuration for encoding, limits, and retries.
        output_dir: Directory where final clips and temporary parts will live.
        db_path: SQLite database path. Defaults to ``config.paths.database``.
        job_id: Existing job id to resume, or None to create a new job.
        on_clip_start: Optional callback when a clip starts (idx_1_based, total).
        on_clip_progress: Optional callback invoked on FFmpeg progress frames.
        on_clip_done: Optional callback invoked when a clip finishes.

    Returns:
        JobResult summarizing the outcome of all clips.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    tmp_dir = output_dir / ".clipforge_tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)

    if db_path is None:
        db_path = config.paths.database

    config_snapshot = {
        "processing": config.processing.model_dump(),
        "output": config.output.model_dump(),
        "optimizer": config.optimizer.model_dump(),
        "quality": config.quality.model_dump(),
        "fault_tolerance": config.fault_tolerance.model_dump(),
        "performance": config.performance.model_dump(),
    }

    # Ensure schema exists before any DB write (RULE-22)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    _schema_conn = sqlite3.connect(str(db_path), timeout=30.0, isolation_level=None)
    try:
        init_schema(_schema_conn)
    finally:
        _schema_conn.close()

    # Create or load the job row (RULE-27: config snapshot per job)
    if job_id is None:
        job_id = create_job(
            db_path, plan.input_path, output_dir, cast(dict[str, object], config_snapshot)
        )

    set_job_state(db_path, job_id, JobState.PROCESSING)

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

            # Insert clip row as PENDING (DB commit before any filesystem work)
            insert_clip(db_path, job_id, clip_idx, boundary.start_us, boundary.duration_us)

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
            source_w = v.display_width if (v and v.display_width) else (v.width if v else 1920)
            source_h = v.display_height if (v and v.display_height) else (v.height if v else 1080)
            source_fps = float(v.avg_frame_rate) if (v and v.avg_frame_rate) else 30.0
            feasibility_verdict = plan.feasibility.verdict if plan.feasibility else "comfortable"

            budget = calculate_budget(
                duration_us=boundary.duration_us,
                audio_bps=audio_bps,
                target_bytes=TARGET_CLIP_SIZE_BYTES,
                height=source_h,
                feasibility_class=feasibility_verdict,
                crf_start=config.optimizer.crf_start,
                crf_max=config.optimizer.crf_max,
            )
            current_video_bps = budget.video_bps
            current_audio_bps = budget.audio_bps
            current_crf = budget.crf
            clip_duration_sec = boundary.duration_us / 1_000_000

            degradation_state = DegradationState()
            q_verdict: QualityVerdict | None = None
            size_attempts = 0
            fault_retries = 0
            total_encodes = 0
            underuse_attempts = 0
            is_two_pass = False
            clip_state = ClipState.PENDING
            error_msg: str | None = None
            final_size = 0
            attempt_number = 0

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

                scale_dims = (
                    (degradation_state.target_width, degradation_state.target_height)
                    if (
                        degradation_state.downscaled
                        and degradation_state.target_width
                        and degradation_state.target_height
                    )
                    else None
                )
                tgt_fps = degradation_state.target_fps if degradation_state.fps_halved else None

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
                        scale_dimensions=scale_dims,
                        target_fps=tgt_fps,
                    )
                    total_encodes += 1
                    attempt_number += 1
                    pass1_res = run_encode(
                        cmd=pass1_cmd,
                        output_part_path=part_path,
                        clip_duration_seconds=clip_duration_sec,
                        timeout=timeout,
                        on_progress=_progress_cb,
                        is_analysis_pass=True,
                    )
                    append_attempt(
                        db_path,
                        job_id,
                        clip_idx,
                        attempt_number,
                        "pass1",
                        "success" if pass1_res.success else "failed",
                        crf=current_crf,
                        duration_seconds=clip_duration_sec,
                        stderr_tail=pass1_res.stderr_tail,
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
                        scale_dimensions=scale_dims,
                        target_fps=tgt_fps,
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
                        scale_dimensions=scale_dims,
                        target_fps=tgt_fps,
                    )

                total_encodes += 1
                attempt_number += 1
                encode_res = run_encode(
                    cmd=cmd,
                    output_part_path=part_path,
                    clip_duration_seconds=clip_duration_sec,
                    timeout=timeout,
                    on_progress=_progress_cb,
                )
                if is_two_pass:
                    _clean_passlogs(tmp_dir, clip_filename)

                append_attempt(
                    db_path,
                    job_id,
                    clip_idx,
                    attempt_number,
                    "encode",
                    "success" if encode_res.success else "failed",
                    size_bytes=encode_res.size_bytes,
                    crf=current_crf,
                    duration_seconds=clip_duration_sec,
                    stderr_tail=encode_res.stderr_tail,
                )

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

                    # Check degradation ladder before declaring FAILED_SIZE (FR-OPT-12)
                    ladder_step = next_degradation_step(
                        degradation_state,
                        config.output.on_oversize,
                        source_w,
                        source_h,
                        source_fps,
                    )
                    if (
                        ladder_step is not None
                        and total_encodes < config.optimizer.max_total_encodes
                    ):
                        degradation_state = ladder_step
                        size_attempts = 0
                        is_two_pass = False
                        part_path.unlink(missing_ok=True)
                        new_h = (
                            degradation_state.target_height
                            if degradation_state.target_height
                            else source_h
                        )
                        new_budget = calculate_budget(
                            duration_us=boundary.duration_us,
                            audio_bps=audio_bps,
                            target_bytes=TARGET_CLIP_SIZE_BYTES,
                            height=new_h,
                            feasibility_class=feasibility_verdict,
                            crf_start=config.optimizer.crf_start,
                            crf_max=config.optimizer.crf_max,
                        )
                        current_video_bps = new_budget.video_bps
                        current_crf = new_budget.crf
                        continue

                    clip_state = ClipState.FAILED_SIZE
                    error_msg = (
                        f"size {actual_size:,} bytes exceeds hard limit "
                        f"{config.output.max_size:,} after {size_attempts} size attempts"
                    )
                    part_path.unlink(missing_ok=True)
                    break

                # Tier 0 Gate: Container, codecs, resolution, and timing (FR-SPL-08)
                exp_fps = (
                    degradation_state.target_fps if degradation_state.fps_halved else source_fps
                )
                exp_w = degradation_state.target_width if degradation_state.downscaled else source_w
                exp_h = (
                    degradation_state.target_height if degradation_state.downscaled else source_h
                )
                tier0 = verify_clip(
                    clip_path=part_path,
                    max_size_bytes=config.output.max_size,
                    expected_duration=clip_duration_sec,
                    expected_fps=exp_fps,
                    expected_width=exp_w,
                    expected_height=exp_h,
                )
                if not tier0.valid:
                    if tier0.timing_mismatch:
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
                            part_path.unlink(missing_ok=True)
                            continue

                        # Survived retries -> marks NEEDS_REVIEW per FR-SPL-08
                        clip_state = ClipState.NEEDS_REVIEW
                        error_msg = f"timing mismatch survived retries: {'; '.join(tier0.errors)}"
                        atomic_publish(part_path, final_path)
                        final_size = actual_size
                        break

                    if (
                        fault_retries < config.fault_tolerance.fault_retries
                        and total_encodes < config.optimizer.max_total_encodes
                    ):
                        fault_retries += 1
                        delays = config.fault_tolerance.retry_delays_seconds
                        delay = delays[min(fault_retries - 1, len(delays) - 1)] if delays else 0.0
                        if delay > 0:
                            time.sleep(delay)
                        part_path.unlink(missing_ok=True)
                        continue

                    clip_state = ClipState.FAILED
                    error_msg = f"clip verification failed: {'; '.join(tier0.errors)}"
                    part_path.unlink(missing_ok=True)
                    break

                # Tier 1/2 Quality Gate (FR-OPT-08..10)
                q_verdict = check_quality_gate(
                    clip_path=part_path,
                    source_path=probe.input_path,
                    start_us=boundary.start_us,
                    duration_us=boundary.duration_us,
                    config=config.quality,
                    clip_index=clip_idx,
                    target_width=degradation_state.target_width,
                    target_height=degradation_state.target_height,
                )

                if not q_verdict.passed:
                    # Under-use check (FR-OPT-11)
                    if check_underuse(
                        actual_size_bytes=actual_size,
                        target_size_bytes=TARGET_CLIP_SIZE_BYTES,
                        quality_passed=False,
                        underuse_attempts=underuse_attempts,
                    ):
                        underuse_attempts += 1
                        current_crf = adjust_crf_for_underuse(current_crf)
                        part_path.unlink(missing_ok=True)
                        continue

                    # Failed quality gate without underuse retry -> mark NEEDS_REVIEW (RULE-45)
                    clip_state = ClipState.NEEDS_REVIEW
                    if q_verdict.score is not None and q_verdict.threshold is not None:
                        error_msg = (
                            f"quality gate failed: {q_verdict.metric} score "
                            f"{q_verdict.score:.4f} < threshold {q_verdict.threshold:.4f}"
                        )
                    else:
                        error_msg = q_verdict.error or "quality gate failed"
                    atomic_publish(part_path, final_path)
                    final_size = actual_size
                    break

                # Atomic publish for fully passing clip (RULE-08, fsync + os.replace)
                atomic_publish(part_path, final_path)
                clip_state = ClipState.COMPLETED
                final_size = actual_size
                break

            # DB commit before filesystem mutation: record clip outcome (RULE-22)
            is_pub = clip_state in (ClipState.COMPLETED, ClipState.NEEDS_REVIEW)
            pub_path = final_path if is_pub else None
            update_clip_state(
                db_path,
                job_id,
                clip_idx,
                clip_state,
                output_path=pub_path,
                size_bytes=final_size,
                size_attempts=size_attempts,
                fault_retries=fault_retries,
                total_encodes=total_encodes,
                two_pass=is_two_pass,
                crf=current_crf,
                error_message=error_msg,
                degradation=degradation_state.steps_applied,
                quality_metric=q_verdict.metric if q_verdict else None,
                quality_score=q_verdict.score if q_verdict else None,
                quality_threshold=q_verdict.threshold if q_verdict else None,
            )

            result = ClipResult(
                index=clip_idx,
                start_us=boundary.start_us,
                duration_us=boundary.duration_us,
                state=clip_state,
                output_path=pub_path,
                size_bytes=final_size,
                size_attempts=size_attempts,
                fault_retries=fault_retries,
                total_encodes=total_encodes,
                two_pass=is_two_pass,
                crf=current_crf,
                error_message=error_msg,
                degradation=degradation_state.steps_applied,
                quality_metric=q_verdict.metric if q_verdict else None,
                quality_score=q_verdict.score if q_verdict else None,
                quality_threshold=q_verdict.threshold if q_verdict else None,
            )
            clip_results.append(result)

            # Job counters + manifest after every clip (RULE-08 style atomicity)
            completed_n = sum(1 for c in clip_results if c.state == ClipState.COMPLETED)
            failed_n = sum(
                1
                for c in clip_results
                if c.state in (ClipState.FAILED, ClipState.FAILED_SIZE, ClipState.FAILED_LIMIT)
            )
            review_n = sum(1 for c in clip_results if c.state == ClipState.NEEDS_REVIEW)
            set_job_counts(db_path, job_id, plan.clip_count, completed_n, failed_n, review_n)

            clip_record = {
                "index": result.index,
                "state": result.state.value,
                "size_bytes": result.size_bytes,
                "path": str(result.output_path) if result.output_path else None,
                "error": result.error_message,
                "degradation": list(result.degradation),
                "quality_metric": result.quality_metric,
                "quality_score": result.quality_score,
            }
            write_manifest(output_dir, job_id, cast(list[dict[str, object]], [clip_record]))

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
            job_state = (
                JobState.COMPLETED_WITH_ISSUES if (completed > 0 or review > 0) else JobState.FAILED
            )
        else:
            job_state = JobState.COMPLETED

    # Commit final job state to the database
    set_job_state(db_path, job_id, job_state)
    set_job_counts(db_path, job_id, plan.clip_count, completed, failed, review)

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
