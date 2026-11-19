"""Budget math, the size loop, the ladder, and quality gates."""

from clipforge.optimizer.budget import (
    ClipBudget,
    calculate_budget,
    default_audio_bitrate_bps,
    select_starting_crf,
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
    "ClipBudget",
    "adjust_crf_for_underuse",
    "calculate_budget",
    "can_retry_size",
    "check_underuse",
    "default_audio_bitrate_bps",
    "is_oversize",
    "recalculate_bitrate",
    "select_starting_crf",
    "should_promote_two_pass",
]

