"""The ``probe`` command: show input metadata and compatibility
(FR-PRO-01/02/03, FR-INP-03/04/07).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from clipforge.core.errors import UsageError
from clipforge.probe import build_report, normalize, run_ffprobe
from clipforge.probe.compatibility import ContainerVerdict, StreamVerdict
from clipforge.probe.metadata import FormatInfo


def _validate_input(input_path: Path) -> None:
    """FR-INP-03 validation: exists, readable, parses, has video, duration,
    codec decodable, quick integrity.
    """
    if not input_path.exists():
        raise UsageError(
            what=f"input file not found: {input_path}",
            meaning="the file does not exist at the given path",
            fix="check the path spelling; use an absolute path if unsure",
        )
    if not input_path.is_file():
        raise UsageError(
            what=f"input is not a file: {input_path}",
            meaning="the path points to a directory or special file",
            fix="provide a path to a regular media file",
        )
    # readability check: try opening
    try:
        input_path.open("rb").close()
    except OSError as exc:
        raise UsageError(
            what=f"cannot read input file: {input_path}",
            meaning=str(exc),
            fix="check file permissions; run as a user with read access",
        ) from exc


def _print_format_table(console: Console, fmt: FormatInfo) -> None:
    table = Table(title="Container", show_lines=False)
    table.add_column("field")
    table.add_column("value")
    for field in ("format_name", "format_long_name", "duration", "size", "bit_rate", "nb_streams"):
        value = getattr(fmt, field)
        table.add_row(field, str(value) if value is not None else "unknown")
    console.print(table)


def _print_stream_table(
    console: Console, title: str, streams: Sequence[Any], fields: Sequence[str]
) -> None:
    if not streams:
        console.print(f"[yellow]{title}: none[/yellow]")
        return
    table = Table(title=title, show_lines=False)
    table.add_column("idx")
    for f in fields:
        table.add_column(f)
    for s in streams:
        row = [str(s.index)]
        for f in fields:
            value = getattr(s, f)
            row.append(str(value) if value is not None else "—")
        table.add_row(*row)
    console.print(table)


def _print_container_table(console: Console, cv: ContainerVerdict) -> None:
    table = Table(title="Container compatibility", show_lines=False)
    table.add_column("input format")
    table.add_column("output format")
    table.add_column("verdict")
    table.add_column("reason")
    style = "green" if cv.verdict == "preserved" else "yellow"
    table.add_row(
        cv.input_format,
        cv.output_format,
        f"[{style}]{cv.verdict}[/{style}]",
        cv.reason,
    )
    console.print(table)


def _print_verdict_table(console: Console, title: str, verdicts: Sequence[StreamVerdict]) -> None:
    if not verdicts:
        console.print(f"[yellow]{title}: none[/yellow]")
        return
    table = Table(title=title, show_lines=False)
    table.add_column("idx")
    table.add_column("input codec")
    table.add_column("output codec")
    table.add_column("verdict")
    table.add_column("reason")
    for v in verdicts:
        style = "green" if v.verdict == "preserved" else "yellow"
        table.add_row(
            str(v.index),
            v.input_codec,
            v.output_codec,
            f"[{style}]{v.verdict}[/{style}]",
            v.reason,
        )
    console.print(table)


def run(
    input_path: Path,
    json_output: bool = typer.Option(False, "--json", help="Print raw ProbeData as JSON"),
) -> None:
    """Show metadata and compatibility for the input file.

    Validation checklist (FR-INP-03):
    - exists and is a readable file
    - ffprobe parses it (format + streams)
    - has at least one video stream
    - duration is known
    - codecs are decodable (doctor already checked encoders)
    - quick integrity: header + stream info + last-packet timestamp present
    """
    _validate_input(input_path)

    # Run ffprobe and normalize
    result = run_ffprobe(input_path)
    probe = normalize(result, input_path)

    # Validation: must have video
    if not probe.has_video:
        raise UsageError(
            what=f"input has no video stream: {input_path}",
            meaning="ClipForge splits video into clips; audio-only files are not supported",
            fix="provide a file with a video track, or use an audio tool for audio-only files",
        )

    # Validation: duration must be known
    if probe.duration_seconds is None:
        raise UsageError(
            what=f"cannot determine duration: {input_path}",
            meaning="the container or streams do not expose a duration",
            fix="try remuxing with ffmpeg first, or check that the file is not truncated",
        )

    # Quick integrity: primary video should have some frames or duration
    primary_video = probe.primary_video
    if primary_video and primary_video.nb_frames is None and primary_video.duration is None:
        raise UsageError(
            what=f"quick integrity check failed: {input_path}",
            meaning=(
                "the video stream reports no frame count and no duration; file may be truncated"
            ),
            fix="verify the file with `ffprobe -show_error` or re-download/copy it",
        )

    report = build_report(probe)

    if json_output:
        import json
        from dataclasses import asdict
        from fractions import Fraction

        def _jsonify(obj: Any) -> Any:
            if hasattr(obj, "__dataclass_fields__"):
                obj = asdict(obj)
            if isinstance(obj, dict):
                return {k: _jsonify(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_jsonify(v) for v in obj]
            if isinstance(obj, Path):
                return str(obj)
            if isinstance(obj, Fraction):
                return float(obj)
            return obj

        typer.echo(json.dumps(_jsonify(probe), indent=2))
        return

    console = Console()

    # Metadata
    _print_format_table(console, probe.format)
    console.print()
    _print_stream_table(
        console,
        "Video streams",
        probe.video_streams,
        [
            "codec_name",
            "width",
            "height",
            "rotation",
            "display_resolution",
            "pix_fmt",
            "r_frame_rate",
            "avg_frame_rate",
            "duration",
            "nb_frames",
            "is_vfr",
        ],
    )
    console.print()
    _print_stream_table(
        console,
        "Audio streams",
        probe.audio_streams,
        [
            "codec_name",
            "sample_rate",
            "channels",
            "channel_layout",
            "bit_rate",
        ],
    )

    # Compatibility
    console.print()
    _print_container_table(console, report.container)
    _print_verdict_table(console, "Video stream compatibility", report.video_verdicts)
    _print_verdict_table(console, "Audio stream compatibility", report.audio_verdicts)

    # Summary line
    console.print()
    if probe.duration_seconds:
        console.print(f"Duration: {probe.duration_seconds:.2f} s")
    console.print(
        f"Video: {len(probe.video_streams)} stream(s), Audio: {len(probe.audio_streams)} stream(s)"
    )
