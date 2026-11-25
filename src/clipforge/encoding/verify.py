"""Post-encode clip verification (Phase 4, RULE-02, FR-OPT-01)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from clipforge.core.constants import MAX_CLIP_SIZE_BYTES
from clipforge.probe.ffprobe import FFprobeError, run_ffprobe


@dataclass(frozen=True)
class ClipVerification:
    """Outcome of validating an encoded clip against constraints."""

    path: Path
    valid: bool
    size_bytes: int
    is_oversize: bool
    format_name: str | None
    video_codec: str | None
    audio_codec: str | None
    duration_seconds: float | None
    errors: list[str]
    timing_mismatch: bool = False
    width: int | None = None
    height: int | None = None


def verify_clip(
    clip_path: Path,
    max_size_bytes: int = MAX_CLIP_SIZE_BYTES,
    expected_duration: float | None = None,
    expected_fps: float | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
) -> ClipVerification:
    """Verify that an encoded clip exists, adheres to the size cap, and is valid WebM.

    Args:
        clip_path: Path to the generated clip file.
        max_size_bytes: Hard ceiling in bytes (default 4,194,304, RULE-02).
        expected_duration: Optional expected duration in seconds to check within tolerance.

    Returns:
        ClipVerification instance with check results and error details.
    """
    errors: list[str] = []

    if not clip_path.exists():
        return ClipVerification(
            path=clip_path,
            valid=False,
            size_bytes=0,
            is_oversize=False,
            format_name=None,
            video_codec=None,
            audio_codec=None,
            duration_seconds=None,
            errors=["file does not exist on disk"],
        )

    size = clip_path.stat().st_size
    if size == 0:
        return ClipVerification(
            path=clip_path,
            valid=False,
            size_bytes=0,
            is_oversize=False,
            format_name=None,
            video_codec=None,
            audio_codec=None,
            duration_seconds=None,
            errors=["file is zero bytes"],
        )

    is_oversize = size > max_size_bytes
    if is_oversize:
        errors.append(f"size {size:,} bytes exceeds hard cap {max_size_bytes:,} bytes")

    # Probe the clip container and streams
    format_name: str | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    duration_seconds: float | None = None
    width: int | None = None
    height: int | None = None
    timing_mismatch = False

    try:
        res = run_ffprobe(clip_path)
        format_name = res.format.get("format_name")
        if not format_name or "webm" not in format_name:
            errors.append(f"container is not WebM: '{format_name}'")

        dur_str = res.format.get("duration")
        if dur_str:
            try:
                duration_seconds = float(dur_str)
            except ValueError:
                duration_seconds = None

        has_video = False
        for s in res.streams:
            codec_type = s.get("codec_type")
            c_name = s.get("codec_name")
            if codec_type == "video":
                has_video = True
                video_codec = c_name
                if c_name != "vp9":
                    errors.append(f"video codec is not vp9: '{c_name}'")
                width = s.get("width")
                height = s.get("height")
            elif codec_type == "audio":
                audio_codec = c_name
                if c_name != "opus":
                    errors.append(f"audio codec is not opus: '{c_name}'")

        if not has_video:
            errors.append("no video stream found in clip")

        # Resolution verification (FR-OPT-12)
        if expected_width is not None and width is not None and width != expected_width:
            errors.append(f"width {width} does not match expected {expected_width}")
        if expected_height is not None and height is not None and height != expected_height:
            errors.append(f"height {height} does not match expected {expected_height}")

        # Timing verification (FR-SPL-08: within 1 frame tolerance)
        if expected_duration is not None and duration_seconds is not None:
            fps = expected_fps or 30.0
            tolerance = (1.0 / fps) + 0.05
            if abs(duration_seconds - expected_duration) > tolerance:
                timing_mismatch = True
                errors.append(
                    f"duration {duration_seconds:.3f} s diverges from "
                    f"expected {expected_duration:.3f} s (> 1 frame tolerance)"
                )

    except FFprobeError as exc:
        errors.append(f"ffprobe failed to inspect clip: {exc.meaning}")

    valid = len(errors) == 0

    return ClipVerification(
        path=clip_path,
        valid=valid,
        size_bytes=size,
        is_oversize=is_oversize,
        format_name=format_name,
        video_codec=video_codec,
        audio_codec=audio_codec,
        duration_seconds=duration_seconds,
        errors=errors,
        timing_mismatch=timing_mismatch,
        width=width,
        height=height,
    )
