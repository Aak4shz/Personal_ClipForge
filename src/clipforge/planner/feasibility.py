"""Feasibility analysis: bits per pixel per frame (FR-OPT-04, RULE-29)."""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from typing import Literal

FeasibilityClass = Literal["comfortable", "tight", "risky"]

FEASIBILITY_THRESHOLDS = {
    "comfortable": 0.04,
    "tight": 0.02,
}


@dataclass(frozen=True)
class FeasibilityEstimate:
    """Bits per pixel per frame feasibility estimate."""

    bpp: float
    verdict: FeasibilityClass
    video_bps: int
    width: int
    height: int
    fps: float
    meaning: str


def estimate_feasibility(
    video_bps: int,
    width: int,
    height: int,
    fps: float | Fraction,
) -> FeasibilityEstimate:
    """Calculate bits per pixel per frame and classify feasibility.

    Args:
        video_bps: Target video bitrate in bits per second.
        width: Video display width in pixels.
        height: Video display height in pixels.
        fps: Frames per second (float or Fraction).

    Returns:
        FeasibilityEstimate with bpp and classification.
    """
    fps_val = float(fps)
    pixels_per_second = width * height * fps_val

    bpp = 0.0 if pixels_per_second <= 0 else video_bps / pixels_per_second

    if bpp >= FEASIBILITY_THRESHOLDS["comfortable"]:
        verdict: FeasibilityClass = "comfortable"
        meaning = "High quality expected; plenty of bitrate for resolution and frame rate"
    elif bpp >= FEASIBILITY_THRESHOLDS["tight"]:
        verdict = "tight"
        meaning = "Moderate quality; may require two passes or size tuning"
    else:
        verdict = "risky"
        meaning = "Very low quality or degradation expected; consider lower resolution or fps"

    return FeasibilityEstimate(
        bpp=round(bpp, 5),
        verdict=verdict,
        video_bps=video_bps,
        width=width,
        height=height,
        fps=fps_val,
        meaning=meaning,
    )
