"""Encoding profiles and VP9 parameter calculators (FR-ENC-02, FR-ENC-03, RULE-29)."""

from __future__ import annotations

import math
from dataclasses import dataclass

from clipforge.core.config import ProfileName


@dataclass(frozen=True)
class ProfileSettings:
    """Concrete settings for an encoding profile."""

    name: ProfileName
    cpu_used: int
    passes: int
    deadline: str = "good"


PROFILES: dict[ProfileName, ProfileSettings] = {
    "fast": ProfileSettings(name="fast", cpu_used=4, passes=1, deadline="good"),
    "balanced": ProfileSettings(name="balanced", cpu_used=2, passes=1, deadline="good"),
    "best": ProfileSettings(name="best", cpu_used=1, passes=2, deadline="good"),
}


def get_profile(name: ProfileName = "balanced") -> ProfileSettings:
    """Return concrete profile settings for given profile name."""
    if name not in PROFILES:
        raise ValueError(f"Unknown profile: {name}. Must be one of {list(PROFILES.keys())}")
    return PROFILES[name]


def calculate_tile_columns(width: int) -> int:
    """Scale tile columns by video resolution (FR-ENC-03).

    - < 1280 (720p and below): 1 (2 columns)
    - 1280 to 3839 (1080p, 1440p): 2 (4 columns)
    - >= 3840 (4K and above): 3 (8 columns)
    """
    if width < 1280:
        return 1
    if width < 3840:
        return 2
    return 3


def calculate_lag_in_frames(width: int, height: int) -> int:
    """Adaptive lookahead lag-in-frames (FR-ENC-03).

    Reduced from default 25 to 16 at 4K to hold RAM usage within limits.
    """
    if width >= 3840 or height >= 2160:
        return 16
    return 25


def calculate_keyframe_interval(duration_seconds: float, fps: float) -> int:
    """Calculate keyframe interval (-g) covering entire clip duration (FR-ENC-04).

    A 10-second clip needs no interior keyframes; every saved keyframe preserves bitrate budget.
    """
    fps_val = max(1.0, float(fps))
    return max(1, math.ceil(duration_seconds * fps_val))
