"""FFmpeg command construction for clip encoding (FR-ENC-01..07, RULE-05, RULE-06, RULE-29)."""

from __future__ import annotations

from pathlib import Path

from clipforge.core.config import ProfileName
from clipforge.encoding.profiles import (
    calculate_keyframe_interval,
    calculate_lag_in_frames,
    calculate_tile_columns,
    get_profile,
)
from clipforge.probe.metadata import ProbeData
from clipforge.utils.timeutil import format_microseconds


def _defend_path(path: Path) -> str:
    """Ensure path begins with / or ./ to prevent flag injection (RULE-06)."""
    p_str = str(path)
    if not p_str.startswith(("/", "./")):
        return f"./{p_str}"
    return p_str


def build_encode_command(
    input_path: Path,
    output_part_path: Path,
    start_us: int,
    duration_us: int,
    video_bps: int,
    audio_bps: int = 64_000,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
    pix_fmt: str = "yuv420p",
    bits_per_raw_sample: int | None = 8,
    has_audio: bool = True,
    audio_channels: int | None = 2,
    audio_channels_policy: str = "keep",
    profile: ProfileName = "balanced",
    crf: int = 32,
    threads: int = 3,
    pass_number: int | None = None,
    passlogfile: Path | None = None,
) -> list[str]:
    """Assemble the full argument list for encoding one clip.

    Args:
        input_path: Path to source media file.
        output_part_path: Destination path with .part extension.
        start_us: Seek offset in integer microseconds.
        duration_us: Clip duration in integer microseconds.
        video_bps: Target video bitrate in bits per second.
        audio_bps: Target audio bitrate in bits per second.
        width: Video display width.
        height: Video display height.
        fps: Frames per second.
        pix_fmt: Source pixel format.
        bits_per_raw_sample: Source bit depth (e.g. 8 or 10).
        has_audio: Whether input contains audio.
        audio_channels: Number of audio channels in source.
        audio_channels_policy: 'keep' or 'stereo'.
        profile: 'fast', 'balanced', or 'best'.
        crf: Quality target for constrained-quality mode.
        threads: Number of CPU threads (default 3).
        pass_number: Optional pass number (1 or 2) for two-pass control.
        passlogfile: Base path for passlogfile if pass_number is set.

    Returns:
        List of command-line arguments ready for subprocess (shell=False).
    """
    p_settings = get_profile(profile)
    tile_columns = calculate_tile_columns(width)
    lag_in_frames = calculate_lag_in_frames(width, height)
    duration_seconds = duration_us / 1_000_000
    keyframe_interval = calculate_keyframe_interval(duration_seconds, fps)

    # Pixel format: Profile 0 (8-bit yuv420p) or Profile 2 (10-bit yuv420p10le)
    is_10_bit = (bits_per_raw_sample is not None and bits_per_raw_sample > 8) or (
        "10" in pix_fmt or "12" in pix_fmt
    )
    target_pix_fmt = "yuv420p10le" if is_10_bit else "yuv420p"

    # Input seek and duration formatted with microsecond precision
    start_time_str = format_microseconds(start_us)
    duration_str = f"{duration_seconds:.6f}"

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-nostdin",
        "-ss",
        start_time_str,
        "-t",
        duration_str,
        "-i",
        _defend_path(input_path),
        "-map",
        "0:v:0",
    ]

    # Video codec settings
    cmd.extend(
        [
            "-c:v",
            "libvpx-vp9",
            "-deadline",
            p_settings.deadline,
            "-cpu-used",
            str(p_settings.cpu_used),
            "-row-mt",
            "1",
            "-threads",
            str(threads),
            "-tile-columns",
            str(tile_columns),
            "-auto-alt-ref",
            "1",
            "-lag-in-frames",
            str(lag_in_frames),
            "-g",
            str(keyframe_interval),
            "-crf",
            str(crf),
            "-b:v",
            str(video_bps),
            "-pix_fmt",
            target_pix_fmt,
        ]
    )

    # Multi-pass rate control flags
    if pass_number is not None:
        cmd.extend(["-pass", str(pass_number)])
        if passlogfile is not None:
            cmd.extend(["-passlogfile", _defend_path(passlogfile)])

    # Pass 1 skips audio and writes null output
    if pass_number == 1:
        cmd.extend(["-progress", "pipe:1", "-an", "-f", "null", "/dev/null"])
        return cmd

    # Audio handling for final or single-pass encode
    if has_audio and audio_bps > 0:
        cmd.extend(["-map", "0:a:0?", "-c:a", "libopus", "-b:a", str(audio_bps)])
        if audio_channels_policy == "stereo" and audio_channels is not None and audio_channels > 2:
            cmd.extend(["-ac", "2"])
    else:
        cmd.append("-an")

    # Output format and destination
    cmd.extend(
        [
            "-progress",
            "pipe:1",
            "-f",
            "webm",
            _defend_path(output_part_path),
        ]
    )

    return cmd


def build_clip_command(
    probe: ProbeData,
    start_us: int,
    duration_us: int,
    video_bps: int,
    output_part_path: Path,
    audio_bps: int = 64_000,
    profile: ProfileName = "balanced",
    crf: int = 32,
    threads: int = 3,
    audio_channels_policy: str = "keep",
    pass_number: int | None = None,
    passlogfile: Path | None = None,
) -> list[str]:
    """Helper to assemble command directly from ProbeData."""
    v = probe.primary_video
    width = v.display_width if (v and v.display_width) else (v.width if v else 1920)
    height = v.display_height if (v and v.display_height) else (v.height if v else 1080)
    fps = float(v.avg_frame_rate) if (v and v.avg_frame_rate) else 30.0
    pix_fmt = v.pix_fmt if v else "yuv420p"
    bits = v.bits_per_raw_sample if v else 8

    a = probe.primary_audio
    has_audio = probe.has_audio and a is not None
    audio_channels = a.channels if a else None

    return build_encode_command(
        input_path=probe.input_path,
        output_part_path=output_part_path,
        start_us=start_us,
        duration_us=duration_us,
        video_bps=video_bps,
        audio_bps=audio_bps,
        width=width,
        height=height,
        fps=fps,
        pix_fmt=pix_fmt,
        bits_per_raw_sample=bits,
        has_audio=has_audio,
        audio_channels=audio_channels,
        audio_channels_policy=audio_channels_policy,
        profile=profile,
        crf=crf,
        threads=threads,
        pass_number=pass_number,
        passlogfile=passlogfile,
    )
