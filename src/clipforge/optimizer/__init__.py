"""Budget math, the size loop, the ladder, and quality gates."""

from clipforge.optimizer.budget import (
    ClipBudget,
    calculate_budget,
    default_audio_bitrate_bps,
)
from clipforge.optimizer.size_loop import (
    can_retry_size,
    is_oversize,
    recalculate_bitrate,
)

__all__ = [
    "ClipBudget",
    "calculate_budget",
    "can_retry_size",
    "default_audio_bitrate_bps",
    "is_oversize",
    "recalculate_bitrate",
]

