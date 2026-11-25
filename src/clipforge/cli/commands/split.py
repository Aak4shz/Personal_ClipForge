"""The ``split`` command: plan and split video into size-capped WebM clips (FR-SPL-01..06).

In Phase 3, this implements `--dry-run` to inspect boundaries, budget, and feasibility
without encoding. Full encoding lands in Phase 5.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.table import Table

from clipforge.core.config import load_config
from clipforge.core.constants import (
    MAX_CLIP_SIZE_BYTES,
    TARGET_CLIP_SIZE_BYTES,
    ClipState,
    ExitCode,
    JobState,
)
from clipforge.core.errors import UsageError
from clipforge.manager.scheduler import ClipResult, run_job
from clipforge.planner.plan import JobPlan, plan_job
from clipforge.probe.ffprobe import run_ffprobe
from clipforge.probe.metadata import normalize
from clipforge.utils.timeutil import format_duration_short, format_microseconds


def _validate_input_file(input_path: Path) -> None:
    """Validate that the input exists, is a regular file, and is readable."""
    if not input_path.exists():
        raise UsageError(
            what=f"input file not found: {input_path}",
            meaning="the file does not exist at the given path",
            fix="check the path spelling; use an absolute path if unsure",
        )
    if not input_path.is_file():
        raise UsageError(
            what=f"input is not a regular file: {input_path}",
            meaning="the path points to a directory or special file",
            fix="provide a path to a regular media file",
        )
    try:
        input_path.open("rb").close()
    except OSError as exc:
        raise UsageError(
            what=f"cannot read input file: {input_path}",
            meaning=str(exc),
            fix="check file permissions; run as a user with read access",
        ) from exc


def _print_dry_run_report(console: Console, plan: JobPlan) -> None:
    """Render a comprehensive dry-run plan report using Rich tables."""
    # 1. Plan Overview Table
    summary_table = Table(title="Job Plan Overview", show_lines=False)
    summary_table.add_column("Property", style="bold cyan")
    summary_table.add_column("Value")

    summary_table.add_row("Input file", str(plan.input_path))
    duration_str = (
        f"{format_microseconds(plan.total_duration_us)} "
        f"({format_duration_short(plan.total_duration_us)})"
    )
    summary_table.add_row("Total duration", duration_str)
    summary_table.add_row(
        "Range start",
        f"{format_microseconds(plan.source_start_us)} ({plan.source_start_us / 1_000_000:.2f} s)",
    )
    summary_table.add_row(
        "Clip duration",
        f"{format_microseconds(plan.clip_duration_us)} ({plan.clip_duration_us / 1_000_000:.1f} s)",
    )
    summary_table.add_row("Clip count", f"[bold green]{plan.clip_count}[/bold green] clips")

    tail_desc: str = plan.tail_decision
    if plan.tail_us > 0:
        tail_desc = f"{plan.tail_decision} ({plan.tail_us / 1_000_000:.3f} s)"
    summary_table.add_row("Tail decision", tail_desc)

    est_mib = plan.estimated_total_bytes / (1024 * 1024)
    summary_table.add_row(
        "Estimated total size",
        f"~{est_mib:.2f} MiB ({plan.estimated_total_bytes:,} bytes @ 5% safety margin)",
    )
    console.print(summary_table)

    # 2. Budget & Bitrates Table
    budget_table = Table(title="Clip Bitrate Budget (per clip)", show_lines=False)
    budget_table.add_column("Component", style="bold")
    budget_table.add_column("Bitrate", justify="right")
    budget_table.add_column("Bytes / 10s clip", justify="right")
    budget_table.add_column("Notes")

    b = plan.budget
    audio_kbps = f"{b.audio_bps / 1000:.1f} kbps" if b.audio_bps > 0 else "none"
    budget_table.add_row(
        "Audio",
        audio_kbps,
        f"{b.audio_bytes:,} B",
        "Opus (subtracted first from budget)",
    )
    budget_table.add_row(
        "Video",
        f"{b.video_bps / 1000:,.1f} kbps",
        f"{(b.target_bytes - b.audio_bytes):,} B",
        f"VP9 ({b.video_bps:,} bps)",
    )
    budget_table.add_row(
        "Target Total",
        f"{(b.audio_bps + b.video_bps) / 1000:,.1f} kbps",
        f"[bold]{b.target_bytes:,} B[/bold]",
        "3.80 MiB target (5% safety margin below 4 MiB)",
    )
    budget_table.add_row(
        "Hard Cap",
        "—",
        f"{MAX_CLIP_SIZE_BYTES:,} B",
        "4.00 MiB strict ceiling (RULE-02)",
    )
    console.print(budget_table)

    # 3. Feasibility Verdict Table
    feas_table = Table(title="Feasibility Estimation", show_lines=False)
    feas_table.add_column("Metric", style="bold")
    feas_table.add_column("Value")
    feas_table.add_column("Verdict / Threshold")

    f = plan.feasibility
    verdict_style = (
        "bold green"
        if f.verdict == "comfortable"
        else "bold yellow"
        if f.verdict == "tight"
        else "bold red"
    )

    feas_table.add_row("Resolution", f"{f.width}x{f.height}", "Display resolution")
    feas_table.add_row("Framerate", f"{f.fps:.2f} fps", "Avg frames per second")
    feas_table.add_row("Bits per pixel (bpp)", f"{f.bpp:.5f}", "Target video bps / (W * H * fps)")
    feas_table.add_row(
        "Verdict",
        f"[{verdict_style}]{f.verdict.upper()}[/{verdict_style}]",
        f"[{verdict_style}]{f.meaning}[/{verdict_style}]",
    )
    console.print(feas_table)

    # 4. Boundary Schedule Summary
    b_table = Table(title=f"Boundary Schedule ({plan.clip_count} clips)", show_lines=False)
    b_table.add_column("Clip #", justify="right")
    b_table.add_column("Start", justify="right")
    b_table.add_column("End", justify="right")
    b_table.add_column("Duration", justify="right")
    b_table.add_column("Interval [start, end)")

    clips = plan.boundaries
    if len(clips) <= 10:
        display_clips = [(i, c) for i, c in enumerate(clips)]
        has_gap = False
    else:
        # Show first 3, last 3
        display_clips = [(i, clips[i]) for i in range(3)]
        has_gap = True

    for _i, c in display_clips:
        b_table.add_row(
            str(c.index),
            format_microseconds(c.start_us),
            format_microseconds(c.end_us),
            f"{c.duration_seconds:.2f} s",
            f"[{c.start_us:,}, {c.end_us:,}) µs",
        )

    if has_gap:
        b_table.add_row("...", "...", "...", "...", f"... ({len(clips) - 6} clips omitted) ...")
        for i in range(len(clips) - 3, len(clips)):
            c = clips[i]
            b_table.add_row(
                str(c.index),
                format_microseconds(c.start_us),
                format_microseconds(c.end_us),
                f"{c.duration_seconds:.2f} s",
                f"[{c.start_us:,}, {c.end_us:,}) µs",
            )

    console.print(b_table)


def _serialize_plan(plan: JobPlan) -> dict[str, Any]:
    """Serialize JobPlan into a JSON-friendly dict."""
    return {
        "input_path": str(plan.input_path),
        "total_duration_us": plan.total_duration_us,
        "total_duration_seconds": plan.total_duration_us / 1_000_000,
        "source_start_us": plan.source_start_us,
        "source_start_seconds": plan.source_start_us / 1_000_000,
        "clip_duration_us": plan.clip_duration_us,
        "clip_duration_seconds": plan.clip_duration_us / 1_000_000,
        "clip_count": plan.clip_count,
        "tail_decision": plan.tail_decision,
        "tail_us": plan.tail_us,
        "tail_seconds": plan.tail_us / 1_000_000,
        "estimated_total_bytes": plan.estimated_total_bytes,
        "budget": {
            "target_bytes": plan.budget.target_bytes,
            "audio_bps": plan.budget.audio_bps,
            "audio_bytes": plan.budget.audio_bytes,
            "video_bps": plan.budget.video_bps,
            "duration_us": plan.budget.duration_us,
        },
        "feasibility": {
            "bpp": plan.feasibility.bpp,
            "verdict": plan.feasibility.verdict,
            "video_bps": plan.feasibility.video_bps,
            "width": plan.feasibility.width,
            "height": plan.feasibility.height,
            "fps": plan.feasibility.fps,
            "meaning": plan.feasibility.meaning,
        },
        "boundaries": [
            {
                "index": b.index,
                "start_us": b.start_us,
                "end_us": b.end_us,
                "start_seconds": b.start_seconds,
                "end_seconds": b.end_seconds,
                "duration_seconds": b.duration_seconds,
            }
            for b in plan.boundaries
        ],
    }


def run(
    input_path: Annotated[
        Path,
        typer.Argument(
            help="Path to the video file to split.",
            show_default=False,
        ),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run",
            "-n",
            help="Plan and display boundaries, budget, and feasibility without encoding (Phase 3).",
        ),
    ] = False,
    duration: Annotated[
        float,
        typer.Option(
            "--duration",
            "-d",
            help="Target clip duration in seconds (1 to 600, default 10.0).",
        ),
    ] = 10.0,
    start: Annotated[
        str | None,
        typer.Option(
            "--start",
            "-s",
            help="Start timestamp or offset to begin splitting from (e.g. '00:01:00', '60s').",
        ),
    ] = None,
    end: Annotated[
        str | None,
        typer.Option(
            "--end",
            "-e",
            help="End timestamp or offset to stop splitting at (e.g. '00:05:00', '300s').",
        ),
    ] = None,
    tail: Annotated[
        str,
        typer.Option(
            "--tail",
            help="Tail policy for orphan segments: 'merge_into_previous', 'keep', or 'drop'.",
        ),
    ] = "merge_into_previous",
    min_tail: Annotated[
        float,
        typer.Option(
            "--min-tail",
            help="Minimum tail threshold in seconds below which a segment is an orphan.",
        ),
    ] = 1.0,
    audio_channels: Annotated[
        str,
        typer.Option(
            "--audio-channels",
            help="Audio channel policy: 'keep' or 'stereo'.",
        ),
    ] = "keep",
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output directory for generated clips (default: ./<video_name>/).",
        ),
    ] = None,
    profile: Annotated[
        str,
        typer.Option(
            "--profile",
            "-p",
            help="Encoding profile: 'fast', 'balanced', or 'best'.",
        ),
    ] = "balanced",
    max_size: Annotated[
        str | None,
        typer.Option(
            "--max-size",
            help="Maximum clip size in bytes or e.g. '4MiB'.",
        ),
    ] = None,
    threads: Annotated[
        int | None,
        typer.Option(
            "--threads",
            help="Number of CPU threads for FFmpeg.",
        ),
    ] = None,
    on_oversize: Annotated[
        str,
        typer.Option(
            "--on-oversize",
            help="Ladder policy on oversize: 'fail', 'fps', 'downscale', or 'both'.",
        ),
    ] = "fail",
    quality_metric: Annotated[
        str,
        typer.Option(
            "--quality-metric",
            help="Quality gate metric: 'none', 'ssim', 'psnr', or 'vmaf'.",
        ),
    ] = "ssim",
    quality_sample: Annotated[
        int,
        typer.Option(
            "--quality-sample",
            help="Evaluate quality gate every N clips (default 1).",
        ),
    ] = 1,
    json_output: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Output the job plan or execution summary as JSON.",
        ),
    ] = False,
) -> None:
    """Plan or run a split into capped clips (Phase 3, Phase 5, Phase 7)."""
    if tail not in ("merge_into_previous", "keep", "drop"):
        raise UsageError(
            what=f"invalid tail policy: '{tail}'",
            meaning="tail policy must be 'merge_into_previous', 'keep', or 'drop'",
            fix="use --tail merge_into_previous, --tail keep, or --tail drop",
        )

    if profile not in ("fast", "balanced", "best"):
        raise UsageError(
            what=f"invalid profile: '{profile}'",
            meaning="profile must be 'fast', 'balanced', or 'best'",
            fix="use --profile fast, --profile balanced, or --profile best",
        )

    if on_oversize not in ("fail", "fps", "downscale", "both"):
        raise UsageError(
            what=f"invalid on-oversize policy: '{on_oversize}'",
            meaning="on-oversize must be 'fail', 'fps', 'downscale', or 'both'",
            fix="use --on-oversize fail|fps|downscale|both",
        )

    if quality_metric not in ("none", "ssim", "psnr", "vmaf"):
        raise UsageError(
            what=f"invalid quality metric: '{quality_metric}'",
            meaning="quality metric must be 'none', 'ssim', 'psnr', or 'vmaf'",
            fix="use --quality-metric none|ssim|psnr|vmaf",
        )

    if quality_sample < 1:
        raise UsageError(
            what=f"invalid quality sample interval: {quality_sample}",
            meaning="quality sample interval must be >= 1",
            fix="use --quality-sample with an integer of 1 or greater",
        )

    _validate_input_file(input_path)

    # Run ffprobe and normalize
    ffprobe_res = run_ffprobe(input_path)
    probe_data = normalize(ffprobe_res, input_path)

    if not probe_data.has_video:
        raise UsageError(
            what=f"input has no video stream: {input_path}",
            meaning="ClipForge splits video into clips; audio-only files are not supported",
            fix="provide a file with a video track",
        )

    if probe_data.duration_seconds is None or probe_data.duration_seconds <= 0:
        raise UsageError(
            what=f"cannot determine duration: {input_path}",
            meaning="the container or streams do not expose a duration",
            fix="try remuxing with ffmpeg first, or check that the file is not truncated",
        )

    plan = plan_job(
        probe=probe_data,
        clip_duration_seconds=duration,
        start_time_spec=start,
        end_time_spec=end,
        tail_policy=tail,  # type: ignore[arg-type]
        min_tail_seconds=min_tail,
        audio_channels_policy=audio_channels,
        target_bytes=TARGET_CLIP_SIZE_BYTES,
    )

    if dry_run:
        if json_output:
            typer.echo(json.dumps(_serialize_plan(plan), indent=2))
        else:
            console = Console()
            _print_dry_run_report(console, plan)
        return

    # Phase 5: MVP full run
    out_dir = output or Path(f"./{input_path.stem}")

    overrides: dict[str, Any] = {
        "processing.clip_duration_seconds": duration,
        "processing.tail_policy": tail,
        "processing.min_tail_seconds": min_tail,
        "output.profile": profile,
        "output.audio_channels": audio_channels,
        "output.on_oversize": on_oversize,
        "quality.metric": quality_metric,
        "quality.sample_every": quality_sample,
    }
    if max_size is not None:
        overrides["output.max_size"] = max_size
    if threads is not None:
        overrides["performance.ffmpeg_threads"] = threads

    cfg = load_config(overrides=overrides)
    console = Console()

    if not json_output:
        console.print(f"[bold cyan]ClipForge Split[/bold cyan]: {input_path.name}")
        console.print(
            f"Target: [green]{out_dir}[/green] ({plan.clip_count} clips @ "
            f"~{plan.clip_duration_us / 1_000_000:.1f} s, profile={profile})\n"
        )

    def _on_clip_start(idx: int, total: int) -> None:
        if not json_output:
            console.print(f"  Encoding clip {idx}/{total}...", end="\r")

    def _on_clip_done(res: ClipResult) -> None:
        if not json_output:
            if res.state == ClipState.COMPLETED:
                size_mib = res.size_bytes / (1024 * 1024)
                console.print(f"  [green]✓[/green] clip_{res.index:04d}.webm ({size_mib:.2f} MiB)")
            else:
                console.print(
                    f"  [red]✗[/red] clip_{res.index:04d}: {res.state.value} - {res.error_message}"
                )

    job_res = run_job(
        plan=plan,
        probe=probe_data,
        config=cfg,
        output_dir=out_dir,
        on_clip_start=_on_clip_start,
        on_clip_done=_on_clip_done,
    )

    if json_output:
        summary = {
            "input_path": str(job_res.input_path),
            "output_dir": str(job_res.output_dir),
            "state": job_res.state.value,
            "total_clips": job_res.total_clips,
            "completed_clips": job_res.completed_clips,
            "failed_clips": job_res.failed_clips,
            "review_clips": job_res.review_clips,
            "clips": [
                {
                    "index": c.index,
                    "state": c.state.value,
                    "size_bytes": c.size_bytes,
                    "path": str(c.output_path) if c.output_path else None,
                    "error": c.error_message,
                    "degradation": list(c.degradation),
                    "quality_metric": c.quality_metric,
                    "quality_score": c.quality_score,
                }
                for c in job_res.clip_results
            ],
        }
        typer.echo(json.dumps(summary, indent=2))
    else:
        if job_res.state == JobState.COMPLETED:
            console.print(
                f"\n[bold green]Complete:[/bold green] All {job_res.completed_clips} clips "
                f"published to [green]{out_dir}[/green]"
            )
        elif job_res.state == JobState.COMPLETED_WITH_ISSUES:
            console.print(
                f"\n[bold yellow]Completed with issues:[/bold yellow] "
                f"{job_res.completed_clips} completed, {job_res.failed_clips} failed"
            )
        elif job_res.state == JobState.INTERRUPTED:
            console.print("\n[bold yellow]Interrupted[/bold yellow]")
        else:
            console.print(
                f"\n[bold red]Job failed:[/bold red] 0/{job_res.total_clips} clips completed"
            )

    if job_res.state == JobState.COMPLETED:
        raise typer.Exit(code=ExitCode.SUCCESS.value)
    elif job_res.state == JobState.COMPLETED_WITH_ISSUES:
        raise typer.Exit(code=ExitCode.COMPLETED_WITH_ISSUES.value)
    elif job_res.state == JobState.INTERRUPTED:
        raise typer.Exit(code=ExitCode.INTERRUPTED.value)
    else:
        raise typer.Exit(code=ExitCode.FATAL.value)
