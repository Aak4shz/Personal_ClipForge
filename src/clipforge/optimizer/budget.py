"""Budget math: target bytes, audio subtraction, video bitrate (FR-OPT-02/03, RULE-29)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from clipforge.core.constants import TARGET_CLIP_SIZE_BYTES


def default_audio_bitrate_bps(channels: int | None) -> int:
    """Return default audio bitrate in bps for given channel count.

    Mono: 40 kbps, Stereo: 64 kbps, 5.1: 160 kbps, 7.1: 224 kbps.
    """
    if channels is None or channels <= 0:
        return 0
    if channels == 1:
        return 40_000
    if channels == 2:
        return 64_000
    if channels <= 6:
        return 160_000
    return 224_000


def select_starting_crf(
    height: int = 1080,
    feasibility_class: str = "comfortable",
    crf_start: int | Literal["auto"] = "auto",
    crf_max: int = 45,
) -> int:
    """Select starting CRF based on resolution and bpp feasibility class (FR-OPT-05).

    Args:
        height: Frame height in pixels.
        feasibility_class: 'comfortable', 'tight', or 'risky'.
        crf_start: Explicit starting CRF or 'auto'.
        crf_max: Hard ceiling on CRF value (default 45).

    Returns:
        Starting CRF clamped to crf_max.
    """
    if isinstance(crf_start, int):
        return min(max(0, crf_start), crf_max)

    if height <= 720:
        crf_map = {"comfortable": 30, "tight": 32, "risky": 36}
    elif height <= 1080:
        crf_map = {"comfortable": 31, "tight": 33, "risky": 37}
    else:
        crf_map = {"comfortable": 32, "tight": 36, "risky": 40}

    chosen = crf_map.get(feasibility_class, 32)
    return min(chosen, crf_max)


@dataclass(frozen=True)
class ClipBudget:
    """Bitrate and byte budget for one clip."""

    target_bytes: int
    audio_bps: int
    audio_bytes: int
    video_bps: int
    duration_us: int
    crf: int = 32

    @property
    def video_kbps(self) -> float:
        return self.video_bps / 1000

    @property
    def audio_kbps(self) -> float:
        return self.audio_bps / 1000


def calculate_budget(
    duration_us: int,
    audio_bps: int = 64_000,
    target_bytes: int = TARGET_CLIP_SIZE_BYTES,
    height: int = 1080,
    feasibility_class: str = "comfortable",
    crf_start: int | Literal["auto"] = "auto",
    crf_max: int = 45,
) -> ClipBudget:
    """Derive video bitrate and starting CRF from byte budget (FR-OPT-02, 03, 05).

    Audio is subtracted first, then video bitrate and starting CRF are calculated.

    Args:
        duration_us: Clip duration in integer microseconds.
        audio_bps: Audio bitrate in bits per second (0 if no audio).
        target_bytes: Byte limit target (default 3,984,589 bytes).
        height: Display height for starting CRF determination.
        feasibility_class: 'comfortable', 'tight', or 'risky'.
        crf_start: Configured starting CRF or 'auto'.
        crf_max: Maximum allowed CRF value.

    Returns:
        ClipBudget instance with exact byte, bitrate, and CRF numbers.

    Raises:
        ValueError: If duration_us <= 0 or audio bytes exceed target bytes.
    """
    if duration_us <= 0:
        raise ValueError(f"duration_us must be positive, got {duration_us}")

    # audio_bytes = audio_bps * duration_seconds / 8
    audio_bytes = (audio_bps * duration_us) // 8_000_000

    if audio_bytes >= target_bytes:
        raise ValueError(
            f"audio budget ({audio_bytes} bytes) exceeds clip target ({target_bytes} bytes)"
        )

    remaining_bytes = target_bytes - audio_bytes

    # video_bps = remaining_bytes * 8 / duration_seconds
    video_bps = (remaining_bytes * 8 * 1_000_000) // duration_us

    crf = select_starting_crf(
        height=height,
        feasibility_class=feasibility_class,
        crf_start=crf_start,
        crf_max=crf_max,
    )

    return ClipBudget(
        target_bytes=target_bytes,
        audio_bps=audio_bps,
        audio_bytes=audio_bytes,
        video_bps=video_bps,
        duration_us=duration_us,
        crf=crf,
    )
