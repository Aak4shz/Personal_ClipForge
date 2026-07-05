"""Unit tests for feasibility estimation and bpp classification (FR-OPT-04, RULE-29)."""

from __future__ import annotations

from fractions import Fraction

from clipforge.planner.feasibility import estimate_feasibility


def test_comfortable_feasibility_1080p30() -> None:
    # 1080p at 30 fps with 3,123,671 bps
    # pixels per second = 1920 * 1080 * 30 = 62,208,000
    # bpp = 3,123,671 / 62,208,000 ≈ 0.05021 >= 0.04
    est = estimate_feasibility(
        video_bps=3_123_671,
        width=1920,
        height=1080,
        fps=30.0,
    )
    assert est.verdict == "comfortable"
    assert est.bpp >= 0.04
    assert round(est.bpp, 4) == 0.0502
    assert "High quality" in est.meaning


def test_tight_feasibility_1080p60() -> None:
    # 1080p at 60 fps with 3,123,671 bps
    # pixels per second = 1920 * 1080 * 60 = 124,416,000
    # bpp = 3,123,671 / 124,416,000 ≈ 0.02511 (between 0.02 and 0.04)
    est = estimate_feasibility(
        video_bps=3_123_671,
        width=1920,
        height=1080,
        fps=60.0,
    )
    assert est.verdict == "tight"
    assert 0.02 <= est.bpp < 0.04
    assert "Moderate quality" in est.meaning


def test_risky_feasibility_4k60() -> None:
    # 4K (3840x2160) at 60 fps with 3,123,671 bps
    # pixels per second = 3840 * 2160 * 60 = 497,664,000
    # bpp = 3,123,671 / 497,664,000 ≈ 0.00628 < 0.02
    est = estimate_feasibility(
        video_bps=3_123_671,
        width=3840,
        height=2160,
        fps=60.0,
    )
    assert est.verdict == "risky"
    assert est.bpp < 0.02
    assert "Very low quality" in est.meaning


def test_fraction_fps_support() -> None:
    est = estimate_feasibility(
        video_bps=3_123_671,
        width=1920,
        height=1080,
        fps=Fraction(30000, 1001),  # 29.97 fps
    )
    assert est.verdict == "comfortable"
    assert round(est.fps, 2) == 29.97


def test_zero_dimensions_or_fps() -> None:
    est = estimate_feasibility(video_bps=3_123_671, width=0, height=0, fps=0)
    assert est.bpp == 0.0
    assert est.verdict == "risky"
