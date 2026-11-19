"""Normalized probe metadata model (FR-PRO-02, FR-PRO-03).

This is a pure data class — no I/O, no logic — so it is fully unit-testable
against recorded ffprobe JSON (RULE-34). The fields mirror the PRD's FR-INP
and the blueprint's ProbeData specification.
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clipforge.probe.ffprobe import FFprobeResult


@dataclass(frozen=True)
class VideoStreamInfo:
    """Normalized video stream metadata."""

    index: int
    codec_name: str
    codec_long_name: str
    profile: str | None
    width: int
    height: int
    coded_width: int
    coded_height: int
    display_aspect_ratio: str | None
    sample_aspect_ratio: str | None
    pix_fmt: str
    bits_per_raw_sample: int | None
    color_space: str | None
    color_range: str | None
    color_primaries: str | None
    color_transfer: str | None
    # r_frame_rate and avg_frame_rate as Fractions for exact math
    r_frame_rate: Fraction
    avg_frame_rate: Fraction
    time_base: Fraction
    start_pts: int | None
    start_time: float | None
    duration_ts: int | None
    duration: float | None
    nb_frames: int | None
    is_vfr: bool
    disposition: dict[str, Any]
    tags: dict[str, str]
    rotation: int = 0
    display_width: int = 0
    display_height: int = 0

    @property
    def display_resolution(self) -> str:
        return f"{self.display_width}x{self.display_height}"


@dataclass(frozen=True)
class AudioStreamInfo:
    """Normalized audio stream metadata."""

    index: int
    codec_name: str
    codec_long_name: str
    profile: str | None
    sample_rate: int | None
    channels: int | None
    channel_layout: str | None
    bit_rate: int | None
    time_base: Fraction
    start_time: float | None
    duration: float | None
    disposition: dict[str, Any]
    tags: dict[str, str]


@dataclass(frozen=True)
class FormatInfo:
    """Normalized container/format metadata."""

    format_name: str
    format_long_name: str
    start_time: float | None
    duration: float | None
    size: int | None
    bit_rate: int | None
    nb_streams: int
    nb_programs: int
    tags: dict[str, str]


@dataclass(frozen=True)
class ProbeData:
    """Complete normalized probe result for one input file.

    This is the single source of truth for all downstream planning.
    """

    input_path: Path
    format: FormatInfo
    video_streams: list[VideoStreamInfo]
    audio_streams: list[AudioStreamInfo]

    @property
    def primary_video(self) -> VideoStreamInfo | None:
        """Return the first video stream (the one we would split)."""
        return self.video_streams[0] if self.video_streams else None

    @property
    def primary_audio(self) -> AudioStreamInfo | None:
        """Return the first audio stream."""
        return self.audio_streams[0] if self.audio_streams else None

    @property
    def has_video(self) -> bool:
        return bool(self.video_streams)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_streams)

    @property
    def duration_seconds(self) -> float | None:
        """Best-effort duration from format, then primary video, then primary audio."""
        if self.format.duration is not None:
            return self.format.duration
        if self.primary_video and self.primary_video.duration is not None:
            return self.primary_video.duration
        if self.primary_audio and self.primary_audio.duration is not None:
            return self.primary_audio.duration
        return None


def _parse_fraction(value: str | None) -> Fraction | None:
    """Parse 'num/den' or 'num' string to Fraction; None stays None."""
    if value is None or value == "N/A" or value == "":
        return None
    try:
        return Fraction(value)
    except (ValueError, ZeroDivisionError):
        return None


def _parse_int(value: Any) -> int | None:
    if value is None or value == "N/A" or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def _parse_float(value: Any) -> float | None:
    if value is None or value == "N/A" or value == "":
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _normalize_disposition(disp: Any) -> dict[str, Any]:
    if not isinstance(disp, dict):
        return {}
    return {k: bool(v) for k, v in disp.items() if isinstance(k, str)}


def _normalize_tags(tags: Any) -> dict[str, str]:
    if not isinstance(tags, dict):
        return {}
    return {str(k): str(v) for k, v in tags.items() if isinstance(k, str)}


def _extract_rotation(s: dict[str, Any]) -> int:
    """Extract stream rotation in degrees from side_data_list or tags."""
    for item in s.get("side_data_list") or []:
        if isinstance(item, dict) and "rotation" in item:
            try:
                rot = int(float(item["rotation"]))
                return ((rot % 360) + 360) % 360
            except (ValueError, TypeError):
                pass
    tags = s.get("tags")
    if isinstance(tags, dict) and "rotate" in tags:
        try:
            rot = int(float(tags["rotate"]))
            return ((rot % 360) + 360) % 360
        except (ValueError, TypeError):
            pass
    return 0


def _video_from_stream(s: dict[str, Any]) -> VideoStreamInfo:
    width = int(s.get("width", 0) or 0)
    height = int(s.get("height", 0) or 0)
    rotation = _extract_rotation(s)
    if rotation in (90, 270):
        display_width, display_height = height, width
    else:
        display_width, display_height = width, height

    return VideoStreamInfo(
        index=int(s["index"]),
        codec_name=s.get("codec_name", ""),
        codec_long_name=s.get("codec_long_name", ""),
        profile=s.get("profile") or None,
        width=width,
        height=height,
        coded_width=int(s.get("coded_width", 0) or 0),
        coded_height=int(s.get("coded_height", 0) or 0),
        display_aspect_ratio=s.get("display_aspect_ratio") or None,
        sample_aspect_ratio=s.get("sample_aspect_ratio") or None,
        pix_fmt=s.get("pix_fmt", ""),
        bits_per_raw_sample=_parse_int(s.get("bits_per_raw_sample")),
        color_space=s.get("color_space") or None,
        color_range=s.get("color_range") or None,
        color_primaries=s.get("color_primaries") or None,
        color_transfer=s.get("color_transfer") or None,
        r_frame_rate=_parse_fraction(s.get("r_frame_rate")) or Fraction(0, 1),
        avg_frame_rate=_parse_fraction(s.get("avg_frame_rate")) or Fraction(0, 1),
        time_base=_parse_fraction(s.get("time_base")) or Fraction(0, 1),
        start_pts=_parse_int(s.get("start_pts")),
        start_time=_parse_float(s.get("start_time")),
        duration_ts=_parse_int(s.get("duration_ts")),
        duration=_parse_float(s.get("duration")),
        nb_frames=_parse_int(s.get("nb_frames")),
        is_vfr=bool(s.get("avg_frame_rate"))
        and bool(s.get("r_frame_rate"))
        and s.get("avg_frame_rate") != s.get("r_frame_rate"),
        disposition=_normalize_disposition(s.get("disposition")),
        tags=_normalize_tags(s.get("tags")),
        rotation=rotation,
        display_width=display_width,
        display_height=display_height,
    )


def _audio_from_stream(s: dict[str, Any]) -> AudioStreamInfo:
    return AudioStreamInfo(
        index=int(s["index"]),
        codec_name=s.get("codec_name", ""),
        codec_long_name=s.get("codec_long_name", ""),
        profile=s.get("profile") or None,
        sample_rate=_parse_int(s.get("sample_rate")),
        channels=_parse_int(s.get("channels")),
        channel_layout=s.get("channel_layout") or None,
        bit_rate=_parse_int(s.get("bit_rate")),
        time_base=_parse_fraction(s.get("time_base")) or Fraction(0, 1),
        start_time=_parse_float(s.get("start_time")),
        duration=_parse_float(s.get("duration")),
        disposition=_normalize_disposition(s.get("disposition")),
        tags=_normalize_tags(s.get("tags")),
    )


def _format_from_section(f: dict[str, Any]) -> FormatInfo:
    return FormatInfo(
        format_name=f.get("format_name", ""),
        format_long_name=f.get("format_long_name", ""),
        start_time=_parse_float(f.get("start_time")),
        duration=_parse_float(f.get("duration")),
        size=_parse_int(f.get("size")),
        bit_rate=_parse_int(f.get("bit_rate")),
        nb_streams=int(f.get("nb_streams", 0) or 0),
        nb_programs=int(f.get("nb_programs", 0) or 0),
        tags=_normalize_tags(f.get("tags")),
    )


def normalize(result: FFprobeResult, input_path: Path) -> ProbeData:
    """Normalize raw ffprobe JSON into ProbeData (pure function, no I/O)."""
    format_info = _format_from_section(result.format)
    video_streams = []
    audio_streams = []
    for s in result.streams:
        codec_type = s.get("codec_type")
        if codec_type == "video":
            video_streams.append(_video_from_stream(s))
        elif codec_type == "audio":
            audio_streams.append(_audio_from_stream(s))
    return ProbeData(
        input_path=input_path,
        format=format_info,
        video_streams=video_streams,
        audio_streams=audio_streams,
    )
