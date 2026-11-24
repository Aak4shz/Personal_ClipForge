"""Unit tests for bitrate recalculation and size retry rules (FR-OPT-06, RULE-15, RULE-34)."""

from __future__ import annotations

from clipforge.core.constants import (
    MAX_CLIP_SIZE_BYTES,
    TARGET_CLIP_SIZE_BYTES,
)
from clipforge.optimizer.budget import select_starting_crf
from clipforge.optimizer.size_loop import (
    adjust_crf_for_underuse,
    can_retry_size,
    check_underuse,
    is_oversize,
    recalculate_bitrate,
    should_promote_two_pass,
)


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


def test_select_starting_crf() -> None:
    # 720p tiers
    assert select_starting_crf(height=720, feasibility_class="comfortable") == 30
    assert select_starting_crf(height=720, feasibility_class="tight") == 32
    assert select_starting_crf(height=720, feasibility_class="risky") == 36

    # 1080p tiers
    assert select_starting_crf(height=1080, feasibility_class="comfortable") == 31
    assert select_starting_crf(height=1080, feasibility_class="tight") == 33
    assert select_starting_crf(height=1080, feasibility_class="risky") == 37

    # 4K tiers (> 1080p)
    assert select_starting_crf(height=2160, feasibility_class="comfortable") == 32
    assert select_starting_crf(height=2160, feasibility_class="tight") == 36
    assert select_starting_crf(height=2160, feasibility_class="risky") == 40

    # Explicit crf_start
    assert select_starting_crf(height=1080, crf_start=28) == 28

    # Capped at crf_max
    assert select_starting_crf(height=2160, feasibility_class="risky", crf_max=35) == 35
    assert select_starting_crf(height=1080, crf_start=50, crf_max=40) == 40


def test_should_promote_two_pass() -> None:
    # 0 or 1 oversize results: stays one-pass
    assert should_promote_two_pass(size_attempts=0) is False
    assert should_promote_two_pass(size_attempts=1) is False

    # 2 or more oversize results: promotes to two-pass (FR-OPT-07)
    assert should_promote_two_pass(size_attempts=2) is True
    assert should_promote_two_pass(size_attempts=3) is True

    # Disabled if two_pass_fallback is False
    assert should_promote_two_pass(size_attempts=2, two_pass_fallback=False) is False


def test_underuse_check_and_crf_adjustment() -> None:
    target = TARGET_CLIP_SIZE_BYTES  # ~3.98 MB
    small_size = int(target * 0.5)  # 50% of budget

    # Quality passed -> no underuse retry
    assert check_underuse(small_size, target, quality_passed=True) is False

    # Quality failed and small size -> underuse retry eligible (FR-OPT-11)
    assert check_underuse(small_size, target, quality_passed=False) is True

    # Quality failed but size near budget (80%) -> not underuse
    large_size = int(target * 0.85)
    assert check_underuse(large_size, target, quality_passed=False) is False

    # Only earns 1 attempt
    assert (
        check_underuse(
            small_size, target, quality_passed=False, underuse_attempts=1, max_underuse_attempts=1
        )
        is False
    )

    # CRF adjustment lowers CRF
    assert adjust_crf_for_underuse(current_crf=32, crf_step=4) == 28
    # Does not drop below crf_min
    assert adjust_crf_for_underuse(current_crf=16, crf_step=4, crf_min=15) == 15
