"""Budget math, the size loop, the ladder, and quality gates."""

from clipforge.optimizer.budget import (
    ClipBudget,
    calculate_budget,
    default_audio_bitrate_bps,
    select_starting_crf,
)
from clipforge.optimizer.ladder import (
    MIN_FPS_FOR_HALVING,
    STANDARD_HEIGHT_STEPS,
    DegradationState,
    calculate_downscaled_dimensions,
    can_halve_fps,
    get_next_height_step,
    next_degradation_step,
)
from clipforge.optimizer.quality import (
    QualityVerdict,
    Tier0Result,
    check_quality_gate,
    check_tier0_gate,
    is_libvmaf_available,
    measure_quality,
    parse_quality_output,
)
from clipforge.optimizer.size_loop import (
    adjust_crf_for_underuse,
    can_retry_size,
    check_underuse,
    is_oversize,
    recalculate_bitrate,
    should_promote_two_pass,
)

__all__ = [
    "MIN_FPS_FOR_HALVING",
    "STANDARD_HEIGHT_STEPS",
    "ClipBudget",
    "DegradationState",
    "QualityVerdict",
    "Tier0Result",
    "adjust_crf_for_underuse",
    "calculate_budget",
    "calculate_downscaled_dimensions",
    "can_halve_fps",
    "can_retry_size",
    "check_quality_gate",
    "check_tier0_gate",
    "check_underuse",
    "default_audio_bitrate_bps",
    "get_next_height_step",
    "is_libvmaf_available",
    "is_oversize",
    "measure_quality",
    "next_degradation_step",
    "parse_quality_output",
    "recalculate_bitrate",
    "select_starting_crf",
    "should_promote_two_pass",
]
