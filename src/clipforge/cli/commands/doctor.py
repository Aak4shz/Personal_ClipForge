"""The ``doctor`` command: dependency diagnostics (FR-BEN-01).

Doctor inspects the installed media stack and reports what it supports. It
never encodes (Phase 1 out-of-scope rule). FFmpeg and FFprobe run from
argument lists with shell=False (RULE-05), from the first call.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import Protocol

from rich.console import Console
from rich.table import Table

from clipforge.core.errors import DependencyError

_EncoderProbe = tuple[str, str]
"""A required encoder's report label and the token that identifies it."""


class Runner(Protocol):
    """What doctor needs from subprocess: one call, one completed process."""

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]: ...


def system_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run a tool with an argument list and no shell (RULE-05)."""
    return subprocess.run(argv, capture_output=True, text=True, check=False, shell=False)


@dataclass(frozen=True)
class Component:
    """One piece of the media stack and what the probe found."""

    name: str
    present: bool
    detail: str
    required: bool = True


@dataclass(frozen=True)
class FormatSupport:
    """One input container family and whether this build can read it."""

    label: str
    present: bool


_REQUIRED_ENCODERS: tuple[_EncoderProbe, ...] = (
    ("libvpx-vp9 encoder", "libvpx-vp9"),
    ("libopus encoder", "libopus"),
)

# Demuxer token per container family; matroska covers mkv and webm
_COMMON_CONTAINERS: tuple[tuple[str, str], ...] = (
    ("mp4, mov, m4v", "mp4"),
    ("mkv, webm", "matroska"),
    ("avi", "avi"),
    ("flv", "flv"),
    ("mpegts", "mpegts"),
    ("wmv, asf", "asf"),
    ("ogg", "ogg"),
    ("wav", "wav"),
)


def _tool_stdout(runner: Runner, argv: list[str]) -> str | None:
    """Return stdout when the tool runs and exits 0; None when absent or broken."""
    try:
        completed = runner(argv)
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout


def _version_line(runner: Runner, tool: str) -> str | None:
    stdout = _tool_stdout(runner, [tool, "-version"])
    if stdout is None:
        return None
    first = stdout.splitlines()[:1]
    return first[0].strip() if first else None


def _has_token(text: str | None, token: str) -> bool:
    if text is None:
        return False
    return re.search(rf"\b{re.escape(token)}\b", text) is not None


def _demuxer_count(text: str | None) -> int:
    """Count demuxer rows, excluding the header and the D.. legend line.

    A row starts with the D flag followed by whitespace before the name, so
    the legend ("D.. = Demuxing supported") never counts as a row.
    """
    if text is None:
        return 0
    return sum(1 for line in text.splitlines() if re.match(r"\s*D\s", line))


def collect(runner: Runner = system_runner) -> list[Component]:
    """Probe every component and return the findings, mocked or real.

    Args:
        runner: The subprocess runner; tests inject a fake one.

    Returns:
        One Component per probed piece of the stack, in report order.
    """
    ffmpeg_line = _version_line(runner, "ffmpeg")
    ffprobe_line = _version_line(runner, "ffprobe")
    ffmpeg_missing = "ffmpeg is missing, so this check could not run"
    encoders = _tool_stdout(runner, ["ffmpeg", "-hide_banner", "-encoders"])
    filters = _tool_stdout(runner, ["ffmpeg", "-hide_banner", "-filters"])
    hwaccels = _tool_stdout(runner, ["ffmpeg", "-hide_banner", "-hwaccels"])

    components = [
        Component("ffmpeg", ffmpeg_line is not None, ffmpeg_line or "not found on PATH"),
        Component("ffprobe", ffprobe_line is not None, ffprobe_line or "not found on PATH"),
    ]
    encoder_sources = (
        (label, _has_token(encoders, token), token) for label, token in _REQUIRED_ENCODERS
    )
    for label, present, token in encoder_sources:
        if present:
            detail = "listed by `ffmpeg -encoders`"
        elif encoders is None:
            detail = ffmpeg_missing
        else:
            detail = f"{token} not listed by `ffmpeg -encoders`"
        components.append(Component(label, present, detail))

    vmaf_present = _has_token(filters, "vmaf")
    if vmaf_present:
        vmaf_detail = "listed by `ffmpeg -filters`"
    elif filters is None:
        vmaf_detail = ffmpeg_missing
    else:
        vmaf_detail = "not listed by `ffmpeg -filters`"
    components.append(Component("libvmaf filter", vmaf_present, vmaf_detail, required=False))

    vaapi_present = _has_token(hwaccels, "vaapi")
    if vaapi_present:
        vaapi_detail = "listed by `ffmpeg -hwaccels`"
    elif hwaccels is None:
        vaapi_detail = ffmpeg_missing
    else:
        vaapi_detail = "not listed by `ffmpeg -hwaccels`"
    components.append(Component("vaapi hwaccel", vaapi_present, vaapi_detail, required=False))
    return components


def container_support(runner: Runner = system_runner) -> tuple[list[FormatSupport], int]:
    """Report which common containers the build can demux, plus the total count.

    Args:
        runner: The subprocess runner; tests inject a fake one.

    Returns:
        The per-family findings and the number of demuxers this build has.
    """
    demuxers = _tool_stdout(runner, ["ffmpeg", "-hide_banner", "-demuxers"])
    families = [
        FormatSupport(label, _has_token(demuxers, token)) for label, token in _COMMON_CONTAINERS
    ]
    return families, _demuxer_count(demuxers)


def _render(components: list[Component], families: list[FormatSupport], demuxers: int) -> None:
    console = Console()
    table = Table(title="clipforge doctor", show_lines=False)
    table.add_column("component")
    table.add_column("status")
    table.add_column("detail")
    for component in components:
        if component.present:
            style = "green"
            status = "present"
        elif component.required:
            style = "red"
            status = "missing"
        else:
            style = "yellow"
            status = "optional, absent"
        table.add_row(component.name, f"[{style}]{status}[/{style}]", component.detail)
    console.print(table)

    formats = Table(title="input containers")
    formats.add_column("family")
    formats.add_column("readable")
    for family in families:
        formats.add_row(
            family.label,
            "[green]yes[/green]" if family.present else "[red]no[/red]",
        )
    console.print(formats)
    console.print(f"demuxers in this build: {demuxers}")


def run() -> None:
    """Print the stack report, then exit 3 if a required component is missing."""
    components = collect()
    families, demuxers = container_support()
    _render(components, families, demuxers)

    missing = [c.name for c in components if c.required and not c.present]
    if missing:
        raise DependencyError(
            what="missing required components: " + ", ".join(missing),
            meaning="ClipForge cannot probe or split video until these are installed",
            fix="install FFmpeg (Arch: sudo pacman -S ffmpeg), then run `clipforge doctor` again",
        )
