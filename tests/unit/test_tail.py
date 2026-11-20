"""Unit tests for tail policy decision logic (FR-SPL-06, RULE-29)."""

from __future__ import annotations

import pytest

from clipforge.planner.tail import decide_tail


def test_zero_or_negative_tail() -> None:
    assert decide_tail(0) == ("none", 0)
    assert decide_tail(-100) == ("none", 0)


def test_tail_above_threshold_is_kept() -> None:
    # 5 seconds tail with 1.0s threshold
    decision, extra = decide_tail(5_000_000, min_tail_us=1_000_000, policy="merge_into_previous")
    assert decision == "kept"
    assert extra == 0


def test_orphan_tail_merged_into_previous() -> None:
    # 0.2 s tail with 1.0s threshold
    tail_us = 200_000
    decision, extra = decide_tail(tail_us, min_tail_us=1_000_000, policy="merge_into_previous")
    assert decision == "merged"
    assert extra == 200_000


def test_orphan_tail_dropped() -> None:
    # 0.2 s tail with 1.0s threshold
    tail_us = 200_000
    decision, extra = decide_tail(tail_us, min_tail_us=1_000_000, policy="drop")
    assert decision == "dropped"
    assert extra == 0


def test_orphan_tail_kept_under_keep_policy() -> None:
    # 0.2 s tail with 1.0s threshold
    tail_us = 200_000
    decision, extra = decide_tail(tail_us, min_tail_us=1_000_000, policy="keep")
    assert decision == "kept"
    assert extra == 0


def test_lone_short_video_is_never_dropped_or_merged() -> None:
    # Video is 0.5 s total: has_previous_clip is False
    tail_us = 500_000
    decision, extra = decide_tail(
        tail_us,
        min_tail_us=1_000_000,
        policy="merge_into_previous",
        has_previous_clip=False,
    )
    assert decision == "kept"
    assert extra == 0

    decision, extra = decide_tail(
        tail_us,
        min_tail_us=1_000_000,
        policy="drop",
        has_previous_clip=False,
    )
    assert decision == "kept"
    assert extra == 0


@pytest.mark.parametrize(
    "tail_sec,min_sec,policy,expected_decision,expected_extra",
    [
        (0.2, 1.0, "merge_into_previous", "merged", 200_000),
        (0.2, 1.0, "drop", "dropped", 0),
        (0.2, 1.0, "keep", "kept", 0),
        (1.0, 1.0, "merge_into_previous", "kept", 0),  # exactly at threshold
        (1.5, 1.0, "merge_into_previous", "kept", 0),
    ],
)
def test_tail_parameterized(
    tail_sec: float,
    min_sec: float,
    policy: str,
    expected_decision: str,
    expected_extra: int,
) -> None:
    decision, extra = decide_tail(
        tail_us=round(tail_sec * 1_000_000),
        min_tail_us=round(min_sec * 1_000_000),
        policy=policy,  # type: ignore[arg-type]
        has_previous_clip=True,
    )
    assert decision == expected_decision
    assert extra == expected_extra
