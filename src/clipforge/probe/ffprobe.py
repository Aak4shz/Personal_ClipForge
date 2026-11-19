"""FFprobe wrapper: JSON output, argument-list subprocess, typed errors (FR-PRO-01).

RULE-05: argument list + shell=False from the first call.
RULE-06: filename defense with -- and file: prefix where the API allows.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clipforge.core.errors import DependencyError, UsageError


@dataclass(frozen=True)
class FFprobeResult:
    """Parsed ffprobe JSON output (format + streams sections)."""

    format: dict[str, Any]
    streams: list[dict[str, Any]]


class FFprobeError(UsageError):
    """ffprobe failed to produce usable JSON for the given input."""

    def __init__(self, input_path: Path, meaning: str, fix: str = "") -> None:
        super().__init__(
            what=f"cannot probe {input_path}",
            meaning=meaning,
            fix=fix or "check that the file exists, is readable, and is a supported media format",
        )
        self.input_path = input_path


def _ffprobe_argv(input_path: Path) -> list[str]:
    """Build the ffprobe argv with JSON output and filename defense (RULE-06).

    The input file must be the LAST argument for ffprobe.
    """
    # -- before positional prevents "-rf" style attacks; file: prefix is supported by ffprobe
    return [
        "ffprobe",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        "--",
        str(input_path),
    ]


def run_ffprobe(input_path: Path) -> FFprobeResult:
    """Run ffprobe on input_path and return parsed JSON, raising typed errors.

    Args:
        input_path: Path to the media file to probe.

    Returns:
        FFprobeResult with format and streams sections.

    Raises:
        FFprobeError: ffprobe missing, unreadable input, non-JSON output, or empty streams.
        DependencyError: ffprobe binary not found on PATH.
    """
    argv = _ffprobe_argv(input_path)
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            shell=False,  # RULE-05
        )
    except FileNotFoundError as exc:
        raise DependencyError(
            what="ffprobe not found on PATH",
            meaning="ClipForge requires ffprobe to analyze input files",
            fix="install FFmpeg (Arch: sudo pacman -S ffmpeg) and ensure ffprobe is on PATH",
        ) from exc

    if completed.returncode != 0:
        stderr_tail = completed.stderr.strip().splitlines()[-3:] if completed.stderr else []
        meaning = "ffprobe exited with code " + str(completed.returncode)
        if stderr_tail:
            meaning += "; stderr: " + " | ".join(stderr_tail)
        raise FFprobeError(input_path, meaning)

    stdout = completed.stdout.strip()
    if not stdout:
        raise FFprobeError(input_path, "ffprobe produced empty output")

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise FFprobeError(
            input_path,
            f"ffprobe output is not valid JSON: {exc}",
            fix="the file may be corrupted or not a supported media format",
        ) from exc

    format_section = data.get("format", {})
    streams = data.get("streams", [])

    if not isinstance(format_section, dict) or not isinstance(streams, list):
        raise FFprobeError(input_path, "ffprobe JSON missing format or streams sections")

    if not streams:
        raise FFprobeError(
            input_path,
            "no streams found in the file",
            fix="the file may be empty or not a media container",
        )

    return FFprobeResult(format=format_section, streams=streams)
