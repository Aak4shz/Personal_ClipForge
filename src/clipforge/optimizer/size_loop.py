"""Size check and bitrate recalculation retry loop (FR-OPT-01, FR-OPT-06, RULE-15, RULE-29)."""

from __future__ import annotations

from clipforge.core.constants import (
    MAX_CLIP_SIZE_BYTES,
    MAX_SIZE_ATTEMPTS,
    MAX_TOTAL_ENCODES,
    TARGET_CLIP_SIZE_BYTES,
)


def is_oversize(size_bytes: int, max_size_bytes: int = MAX_CLIP_SIZE_BYTES) -> bool:
    """Return True if the size exceeds the hard clip ceiling."""
    return size_bytes > max_size_bytes


def recalculate_bitrate(
    current_video_bps: int,
    actual_size_bytes: int,
    target_size_bytes: int = TARGET_CLIP_SIZE_BYTES,
    min_drop_percent: float = 3.0,
) -> int:
    """Recalculate video bitrate after an oversize encode, always dropping at least 3%.

    Args:
        current_video_bps: The video bitrate used in the prior attempt.
        actual_size_bytes: The resulting file size in bytes.
        target_size_bytes: The desired clip target size in bytes (default 5% under hard cap).
        min_drop_percent: Minimum percentage to reduce bitrate by (default 3.0%).

    Returns:
        New video bitrate in bits per second, at least min_drop_percent lower than current.
    """
    if current_video_bps <= 0:
        return 1

    # Floor ceiling: must be at least min_drop_percent lower than current bitrate
    floor_factor = 1.0 - (min_drop_percent / 100.0)
    max_allowed_bps = int(current_video_bps * floor_factor)

    if actual_size_bytes <= 0:
        return max(1, max_allowed_bps)

    ratio = target_size_bytes / actual_size_bytes
    scaled_bps = int(current_video_bps * ratio)

    # Take the lower of the scaled bitrate and the minimum 3% drop floor
    new_bps = min(scaled_bps, max_allowed_bps)
    return max(1, new_bps)


def can_retry_size(
    size_attempts: int,
    total_encodes: int,
    max_size_attempts: int = MAX_SIZE_ATTEMPTS,
    max_total_encodes: int = MAX_TOTAL_ENCODES,
) -> bool:
    """Check if another size retry is permitted under RULE-15 caps."""
    return size_attempts < max_size_attempts and total_encodes < max_total_encodes


def should_promote_two_pass(
    size_attempts: int,
    two_pass_fallback: bool = True,
) -> bool:
    """Check if clip should be promoted to two-pass rate control (FR-OPT-07).

    A clip is promoted after two oversize results (size_attempts >= 2).
    """
    return two_pass_fallback and size_attempts >= 2


def check_underuse(
    actual_size_bytes: int,
    target_size_bytes: int = TARGET_CLIP_SIZE_BYTES,
    quality_passed: bool = True,
    underuse_ratio: float = 0.75,
    underuse_attempts: int = 0,
    max_underuse_attempts: int = 1,
) -> bool:
    """Return True if output is far below budget and failed quality gate (FR-OPT-11).

    Output far below budget that still fails its quality gate earns one attempt
    at a lower CRF.
    """
    if quality_passed:
        return False
    if underuse_attempts >= max_underuse_attempts:
        return False
    return actual_size_bytes < int(target_size_bytes * underuse_ratio)


def adjust_crf_for_underuse(
    current_crf: int,
    crf_step: int = 4,
    crf_min: int = 15,
) -> int:
    """Lower CRF to improve quality when under-use occurs (FR-OPT-11)."""
    return max(crf_min, current_crf - crf_step)
