"""Unit tests for bitrate recalculation and size retry rules (FR-OPT-06, RULE-15, RULE-34)."""

from __future__ import annotations

from clipforge.core.constants import (
    MAX_CLIP_SIZE_BYTES,
    TARGET_CLIP_SIZE_BYTES,
)
from clipforge.optimizer.size_loop import can_retry_size, is_oversize, recalculate_bitrate


def test_is_oversize() -> None:
    assert not is_oversize(MAX_CLIP_SIZE_BYTES)
    assert not is_oversize(MAX_CLIP_SIZE_BYTES - 1)
    assert not is_oversize(TARGET_CLIP_SIZE_BYTES)
    assert is_oversize(MAX_CLIP_SIZE_BYTES + 1)
    assert is_oversize(5 * 1024 * 1024)


def test_recalc_always_at_least_three_percent_lower() -> None:
    current_bps = 3_000_000
    three_pct_drop = int(current_bps * 0.97)

    # 1. When overshoot is tiny (e.g. 0.1% over target), 3% floor applies
    tiny_overshoot_size = int(TARGET_CLIP_SIZE_BYTES * 1.001)
    new_bps = recalculate_bitrate(current_bps, tiny_overshoot_size)
    assert new_bps <= three_pct_drop
    assert new_bps == three_pct_drop

    # 2. When actual size is exactly target, still enforces 3% reduction
    new_bps_exact = recalculate_bitrate(current_bps, TARGET_CLIP_SIZE_BYTES)
    assert new_bps_exact <= three_pct_drop

    # 3. When actual size is below target, still enforces 3% reduction
    new_bps_under = recalculate_bitrate(current_bps, TARGET_CLIP_SIZE_BYTES - 100_000)
    assert new_bps_under <= three_pct_drop


def test_recalc_large_overshoot_scales_proportionally() -> None:
    current_bps = 3_000_000
    # 2x target size -> ratio is 0.5
    actual_size = TARGET_CLIP_SIZE_BYTES * 2
    new_bps = recalculate_bitrate(current_bps, actual_size)

    expected = int(current_bps * 0.5)
    assert new_bps == expected
    # Much lower than 3% drop
    assert new_bps < int(current_bps * 0.97)


def test_recalc_edge_cases() -> None:
    # Zero or negative current bitrate
    assert recalculate_bitrate(0, 5_000_000) == 1
    assert recalculate_bitrate(-100, 5_000_000) == 1

    # Zero actual size
    assert recalculate_bitrate(1_000_000, 0) == 970_000

    # Very small bitrate does not drop below 1
    assert recalculate_bitrate(1, 10_000_000) == 1


def test_can_retry_size_caps() -> None:
    # Initial attempt: attempt 0, encodes 1
    assert can_retry_size(size_attempts=0, total_encodes=1) is True

    # 3 size attempts, 3 encodes -> can retry (limit is 4)
    assert can_retry_size(size_attempts=3, total_encodes=3) is True

    # 4 size attempts reached -> cannot retry
    assert can_retry_size(size_attempts=4, total_encodes=4) is False

    # 8 total encodes reached -> cannot retry even if size_attempts < 4
    assert can_retry_size(size_attempts=2, total_encodes=8) is False

    # Respects custom caps if passed
    assert can_retry_size(size_attempts=2, total_encodes=3, max_size_attempts=2) is False
    assert can_retry_size(size_attempts=1, total_encodes=5, max_total_encodes=5) is False
