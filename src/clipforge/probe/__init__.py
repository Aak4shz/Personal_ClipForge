"""Input analysis: the ffprobe wrapper, metadata, and compatibility."""

from __future__ import annotations

from clipforge.probe.compatibility import (
    CompatibilityReport,
    StreamVerdict,
    build_report,
)
from clipforge.probe.ffprobe import FFprobeResult, run_ffprobe
from clipforge.probe.metadata import (
    AudioStreamInfo,
    FormatInfo,
    ProbeData,
    VideoStreamInfo,
    normalize,
)

__all__ = [
    "AudioStreamInfo",
    "CompatibilityReport",
    "FFprobeResult",
    "FormatInfo",
    "ProbeData",
    "StreamVerdict",
    "VideoStreamInfo",
    "build_report",
    "normalize",
    "run_ffprobe",
]
