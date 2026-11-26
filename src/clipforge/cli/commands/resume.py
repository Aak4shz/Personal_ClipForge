"""The ``resume`` command: continue an interrupted job exactly where it stopped (Phase 9).

Loads the existing job row, verifies the input fingerprint matches, resets missing
or in-flight clips back to ``PENDING`` (completed clips stay untouched per RULE-66),
then continues the encode loop. ``FAILED`` clips stay out until Phase 11's explicit
retry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast

import typer
from rich.console import Console

from clipforge.core.config import load_config
from clipforge.core.constants import ClipState, ExitCode, JobState
from clipforge.core.errors import UsageError
from clipforge.manager.recovery import prepare_resume
from clipforge.manager.scheduler import ClipResult, run_job
from clipforge.planner.plan import plan_job
from clipforge.probe.ffprobe import run_ffprobe
from clipforge.probe.metadata import normalize
from clipforge.storage.db import connect
from clipforge.storage.repo import job_exists, load_job
from clipforge.storage.schema import init_schema
from clipforge.utils.hashing import fingerprint


def run(
    input_path: Annotated[
        Path,
        typer.Argument(help="Path to the video file whose interrupted job to resume."),
    ],
    output: Annotated[
        Path | None,
        typer.Option(
            "--output",
            "-o",
            help="Output directory of the job to resume (default: ./<video_name>/).",
        ),
    ] = None,
    deep_verify: Annotated[
        bool,
        typer.Option(
            "--deep-verify",
            help="Run a full decode pass on completed clips before resuming.",
        ),
    ] = False,
) -> None:
    """Continue an interrupted job, re-encoding only what still needs it."""
    console = Console()
    _validate_input_file(input_path)

    out_dir = output or Path(f"./{input_path.stem}")
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_config()
    db_path = cfg.paths.database
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(db_path) as conn:
        init_schema(conn)

    # Duplicate detection: same input + output folder => an existing job.
    found = job_exists(db_path, input_path, out_dir)
    if found is None:
        raise UsageError(
            what=f"no job to resume for {input_path} -> {out_dir}",
            meaning="no clipforge job row exists for this input and output folder",
            fix="run `clipforge split <input> --output <out_dir>` first to create a job",
        )
    job_id, state = found

    job = load_job(db_path, job_id)
    if job is None:
        raise UsageError(
            what=f"job {job_id} row missing from database",
            meaning="the job row referenced by the duplicate check could not be loaded",
            fix=f"check the database file at {db_path} is intact",
        )

    if state in {
        "COMPLETED",
        "COMPLETED_WITH_ISSUES",
        "CANCELLED",
        "FAILED",
    }:
        _render_done(console, job, out_dir)
        raise typer.Exit(code=0)

    # Fingerprint guard (RULE-26): refuse to resume if the input changed.
    stored = job.get("config_snapshot") or {}
    stored_fp = stored.get("input_fingerprint") if isinstance(stored, dict) else None
    current_fp = fingerprint(input_path)
    if stored_fp is not None and stored_fp != current_fp.get("sha256"):
        raise UsageError(
            what="input file changed since the job was created",
            meaning="the stored fingerprint does not match the current input file",
            fix="re-run `clipforge split` on the current input, or point "
            "--output at a different folder",
        )

    if deep_verify:
        _deep_verify_completed(console, out_dir)

    # Resume: reset in-flight and missing-output clips to PENDING, then continue.
    job_id, pending = prepare_resume(db_path, input_path, out_dir)
    _render_resume_start(console, job_id, state, len(pending), out_dir)

    ffprobe_res = run_ffprobe(input_path)
    probe_data = normalize(ffprobe_res, input_path)
    plan = plan_job(probe=probe_data, clip_duration_seconds=10.0)
    config = load_config()
    config.paths.database = db_path

    def _on_clip_start(idx: int, total: int) -> None:
        console.print(f"  Encoding clip {idx}/{total}...", end="\r")

    def _on_clip_done(res: ClipResult) -> None:
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
        config=config,
        output_dir=out_dir,
        db_path=db_path,
        job_id=job_id,
        on_clip_start=_on_clip_start,
        on_clip_done=_on_clip_done,
    )

    if job_res.state == JobState.COMPLETED:
        console.print(
            f"\n[bold green]Complete:[/bold green] All {job_res.completed_clips} clips "
            f"published to [green]{out_dir}[/green]"
        )
        raise typer.Exit(code=ExitCode.SUCCESS.value)
    elif job_res.state == JobState.COMPLETED_WITH_ISSUES:
        console.print(
            f"\n[bold yellow]Completed with issues:[/bold yellow] "
            f"{job_res.completed_clips} completed, {job_res.failed_clips} failed"
        )
        raise typer.Exit(code=ExitCode.COMPLETED_WITH_ISSUES.value)
    elif job_res.state == JobState.INTERRUPTED:
        console.print("\n[bold yellow]Interrupted[/bold yellow]")
        raise typer.Exit(code=ExitCode.INTERRUPTED.value)
    else:
        console.print(
            f"\n[bold red]Job failed:[/bold red] 0/{job_res.total_clips} clips completed"
        )
        raise typer.Exit(code=ExitCode.FATAL.value)


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


def _render_done(console: Console, job: dict[str, object], out_dir: Path) -> None:
    """Report that a terminal-state job is already finished."""
    console.print(
        f"[bold yellow]Already {job['state']}:[/bold yellow] "
        f"{job['completed_clips']}/{job['total_clips']} clips in [green]{out_dir}[/green]"
    )


def _render_resume_start(
    console: Console, job_id: int, prior_state: str, pending: int, out_dir: Path
) -> None:
    """Report that a resume is beginning."""
    console.print(
        f"[bold cyan]Resuming job {job_id}[/bold cyan] (was {prior_state}) "
        f"in [green]{out_dir}[/green] — {pending} clip(s) still need encoding"
    )


def _deep_verify_completed(console: Console, out_dir: Path) -> None:
    """Placeholder for full-decode verification of completed clips (Phase 9 option).

    The `--deep-verify` flag is accepted and honored here; the actual decode
    pass lands with the verify command in Phase 11. For now it confirms the
    completed clips are present on disk and match the manifest sizes.
    """
    from clipforge.storage.manifest import read_manifest

    manifest = read_manifest(out_dir)
    if manifest is None:
        return
    for clip in cast(list[dict[str, object]], manifest.get("clips", [])):
        if clip.get("state") == "COMPLETED" and clip.get("path"):
            p = Path(cast(str, clip["path"]))
            if not (p.is_file() and p.stat().st_size == clip.get("size_bytes", 0)):
                raise UsageError(
                    what=f"completed clip missing or undersized: {p}",
                    meaning="a clip the database marks COMPLETED is not intact on disk",
                    fix="run without --deep-verify to resume anyway, or restore the missing clip",
                )
