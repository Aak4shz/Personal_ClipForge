"""Job planning orchestrator (Phase 3)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipforge.core.config import TailPolicy
from clipforge.core.constants import TARGET_CLIP_SIZE_BYTES
from clipforge.core.errors import UsageError
from clipforge.optimizer.budget import ClipBudget, calculate_budget, default_audio_bitrate_bps
from clipforge.planner.boundaries import ClipBoundary, calculate_boundaries
from clipforge.planner.feasibility import FeasibilityEstimate, estimate_feasibility
from clipforge.planner.tail import TailDecision, decide_tail
from clipforge.probe.metadata import ProbeData
from clipforge.utils.timeutil import parse_time_to_microseconds


@dataclass(frozen=True)
class JobPlan:
    """Complete plan for splitting a media file."""

    input_path: Path
    total_duration_us: int
    source_start_us: int
    clip_duration_us: int
    boundaries: list[ClipBoundary]
    tail_decision: TailDecision
    tail_us: int
    budget: ClipBudget
    feasibility: FeasibilityEstimate
    estimated_total_bytes: int

    @property
    def clip_count(self) -> int:
        return len(self.boundaries)


def plan_job(
    probe: ProbeData,
    clip_duration_seconds: float = 10.0,
    start_time_spec: str | None = None,
    end_time_spec: str | None = None,
    tail_policy: TailPolicy = "merge_into_previous",
    min_tail_seconds: float = 1.0,
    audio_channels_policy: str = "keep",
    target_bytes: int = TARGET_CLIP_SIZE_BYTES,
    source_start_us: int = 0,
) -> JobPlan:
    """Plan the splitting of a media file without performing any encode (Phase 3).

    Args:
        probe: Normalized ProbeData for the input file.
        clip_duration_seconds: Target clip duration (1 to 600 s).
        start_time_spec: Optional start range constraint (e.g. '00:01:00').
        end_time_spec: Optional end range constraint (e.g. '00:05:00').
        tail_policy: 'merge_into_previous', 'keep', or 'drop'.
        min_tail_seconds: Threshold below which a tail is considered an orphan.
        audio_channels_policy: 'keep' or 'stereo'.
        target_bytes: Internal byte limit target per clip (default 3,984,589).

    Returns:
        JobPlan instance.

    Raises:
        UsageError: If range specifications or durations are invalid.
    """
    if clip_duration_seconds < 1.0 or clip_duration_seconds > 600.0:
        raise UsageError(
            what=f"invalid clip duration: {clip_duration_seconds} s",
            meaning="clip duration must be between 1 and 600 seconds (FR-SPL-01)",
            fix="pass --duration between 1 and 600",
        )

    if probe.duration_seconds is None or probe.duration_seconds <= 0:
        raise UsageError(
            what=f"cannot plan job for {probe.input_path}: unknown duration",
            meaning="file duration could not be determined",
            fix="ensure the file is valid and readable",
        )

    source_total_us = round(probe.duration_seconds * 1_000_000)

    # Range constraints (FR-INP-08)
    range_start_us = source_start_us
    if start_time_spec is not None:
        range_start_us = parse_time_to_microseconds(start_time_spec)

    range_end_us = source_total_us
    if end_time_spec is not None:
        range_end_us = parse_time_to_microseconds(end_time_spec)

    if range_start_us >= range_end_us:
        raise UsageError(
            what=f"invalid range: start ({range_start_us} µs) >= end ({range_end_us} µs)",
            meaning="the requested start time is at or after the end time",
            fix="ensure --start is earlier than --end",
        )

    if range_start_us >= source_total_us:
        raise UsageError(
            what=(
                f"start time ({start_time_spec}) exceeds video duration "
                f"({probe.duration_seconds:.2f} s)"
            ),
            meaning="the requested start time is past the end of the video",
            fix="choose a start time within the video duration",
        )

    if range_end_us > source_total_us:
        range_end_us = source_total_us

    effective_duration_us = range_end_us - range_start_us
    clip_duration_us = round(clip_duration_seconds * 1_000_000)
    min_tail_us = round(min_tail_seconds * 1_000_000)

    # Boundaries
    boundaries = calculate_boundaries(
        duration_us=effective_duration_us,
        clip_duration_us=clip_duration_us,
        source_start_us=range_start_us,
        tail_policy=tail_policy,
        min_tail_us=min_tail_us,
    )

    tail_us = effective_duration_us % clip_duration_us
    decision, _ = decide_tail(
        tail_us=tail_us,
        min_tail_us=min_tail_us,
        policy=tail_policy,
        has_previous_clip=(effective_duration_us >= clip_duration_us),
    )

    # Audio budget
    channels = probe.primary_audio.channels if probe.primary_audio else 0
    if audio_channels_policy == "stereo" and channels and channels > 2:
        channels = 2
    audio_bps = default_audio_bitrate_bps(channels)

    # Budget (based on standard clip duration)
    budget = calculate_budget(
        duration_us=clip_duration_us,
        audio_bps=audio_bps,
        target_bytes=target_bytes,
    )

    # Feasibility
    v = probe.primary_video
    width = v.display_width if (v and v.display_width) else (v.width if v else 1920)
    height = v.display_height if (v and v.display_height) else (v.height if v else 1080)
    fps = v.avg_frame_rate if (v and v.avg_frame_rate) else (v.r_frame_rate if v else 30.0)

    feasibility = estimate_feasibility(
        video_bps=budget.video_bps,
        width=width,
        height=height,
        fps=fps,
    )

    estimated_total_bytes = len(boundaries) * target_bytes

    return JobPlan(
        input_path=probe.input_path,
        total_duration_us=effective_duration_us,
        source_start_us=range_start_us,
        clip_duration_us=clip_duration_us,
        boundaries=boundaries,
        tail_decision=decision,
        tail_us=tail_us,
        budget=budget,
        feasibility=feasibility,
        estimated_total_bytes=estimated_total_bytes,
    )
