"""Budget math: target bytes, audio subtraction, video bitrate (FR-OPT-02/03, RULE-29)."""

from __future__ import annotations

from dataclasses import dataclass

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


@dataclass(frozen=True)
class ClipBudget:
    """Bitrate and byte budget for one clip."""

    target_bytes: int
    audio_bps: int
    audio_bytes: int
    video_bps: int
    duration_us: int

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
) -> ClipBudget:
    """Derive video bitrate from byte budget with audio subtracted first (FR-OPT-02, FR-OPT-03).

    Args:
        duration_us: Clip duration in integer microseconds.
        audio_bps: Audio bitrate in bits per second (0 if no audio).
        target_bytes: Byte limit target (default 3,984,589 bytes).

    Returns:
        ClipBudget instance with exact byte and bitrate numbers.

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

    return ClipBudget(
        target_bytes=target_bytes,
        audio_bps=audio_bps,
        audio_bytes=audio_bytes,
        video_bps=video_bps,
        duration_us=duration_us,
    )
