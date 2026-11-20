"""FFmpeg progress parsing from -progress pipe:1 (ARCHITECTURE.md 4.5)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SPEED_PATTERN = re.compile(r"^([\d.]+)x?$")


@dataclass(frozen=True)
class ProgressFrame:
    """One progress snapshot parsed from FFmpeg."""

    frame: int = 0
    fps: float = 0.0
    bitrate_kbps: float = 0.0
    total_size_bytes: int = 0
    out_time_us: int = 0
    speed: float = 0.0
    is_end: bool = False

    @property
    def out_time_seconds(self) -> float:
        return self.out_time_us / 1_000_000


def parse_progress_chunk(lines: list[str]) -> ProgressFrame | None:
    """Parse a block of key=value lines from FFmpeg -progress pipe:1.

    Args:
        lines: List of raw output lines from FFmpeg stdout.

    Returns:
        ProgressFrame if lines contained a progress chunk, else None.
    """
    data: dict[str, Any] = {}
    for line in lines:
        line = line.strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        data[key.strip()] = val.strip()

    if not data:
        return None

    # Parse fields defensively
    frame = int(data.get("frame", 0)) if data.get("frame", "").isdigit() else 0

    fps = 0.0
    try:
        fps = float(data.get("fps", 0.0))
    except (ValueError, TypeError):
        fps = 0.0

    # Parse bitrate (e.g. '3123.5kbits/s')
    bitrate_kbps = 0.0
    raw_br = data.get("bitrate", "")
    if raw_br:
        clean_br = raw_br.replace("kbits/s", "").replace("kb/s", "").strip()
        try:
            bitrate_kbps = float(clean_br)
        except ValueError:
            bitrate_kbps = 0.0

    total_size = 0
    raw_size = data.get("total_size", "")
    if raw_size and raw_size.isdigit():
        total_size = int(raw_size)

    # out_time_us or out_time_ms (FFmpeg uses out_time_us in modern builds)
    out_time_us = 0
    raw_time_us = data.get("out_time_us", "")
    if raw_time_us and (raw_time_us.isdigit() or raw_time_us.startswith("-")):
        out_time_us = int(raw_time_us)

    # Speed (e.g. '1.5x' or '1.5')
    speed = 0.0
    raw_speed = data.get("speed", "")
    if raw_speed:
        m = _SPEED_PATTERN.match(raw_speed.strip())
        if m:
            try:
                speed = float(m.group(1))
            except ValueError:
                speed = 0.0

    is_end = data.get("progress") == "end"

    return ProgressFrame(
        frame=frame,
        fps=fps,
        bitrate_kbps=bitrate_kbps,
        total_size_bytes=total_size,
        out_time_us=out_time_us,
        speed=speed,
        is_end=is_end,
    )
