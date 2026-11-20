"""Tail policy implementation (FR-SPL-06, RULE-29)."""

from __future__ import annotations

from typing import Literal

from clipforge.core.config import TailPolicy

TailDecision = Literal["none", "kept", "merged", "dropped"]


def decide_tail(
    tail_us: int,
    min_tail_us: int = 1_000_000,
    policy: TailPolicy = "merge_into_previous",
    has_previous_clip: bool = True,
) -> tuple[TailDecision, int]:
    """Decide the outcome for a remaining tail segment.

    Args:
        tail_us: Length of remaining tail in microseconds.
        min_tail_us: Threshold below which a tail is considered an orphan (default 1.0 s).
        policy: 'keep', 'merge_into_previous', or 'drop'.
        has_previous_clip: Whether there is a preceding clip to merge into.

    Returns:
        (decision, extra_us_for_previous_clip)
        where decision is one of 'none', 'kept', 'merged', 'dropped'.
    """
    if tail_us <= 0:
        return "none", 0

    # If the tail is at or above the threshold, it forms its own clip
    if tail_us >= min_tail_us:
        return "kept", 0

    # Tail is below min_tail_us (an orphan tail)
    if not has_previous_clip:
        # Cannot merge or drop the only content of the video
        return "kept", 0

    if policy == "merge_into_previous":
        return "merged", tail_us

    if policy == "drop":
        return "dropped", 0

    # Policy 'keep': keep even if below threshold
    return "kept", 0
