"""Typer app assembly and entry point (ARCHITECTURE.md 4.2).

The CLI layer parses, validates, and renders results and errors; it holds no
processing logic. Uncaught ClipForgeError instances render here with the exit
code from the documented table (FR-CLI-02).
"""

from __future__ import annotations

import typer

from clipforge import __version__
from clipforge.cli.commands import (
    batch,
    benchmark,
    cancel,
    clean,
    config,
    doctor,
    info,
    probe,
    queue,
    report,
    reprocess,
    resume,
    retry,
    split,
    status,
    verify,
)
from clipforge.cli.exit_codes import ExitCode
from clipforge.core.errors import (
    ClipForgeError,
    DependencyError,
    FatalJobError,
    OversizeResult,
    PermanentClipError,
    QualityGateFail,
    TransientFault,
    UsageError,
)

app = typer.Typer(
    help="Split local videos into verified 10-second WebM clips, each under a hard size cap.",
    no_args_is_help=True,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"clipforge {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the ClipForge version and exit.",
    ),
) -> None:
    """ClipForge: offline splitting into size-capped, verified WebM clips."""


# Registration order follows FR-CLI-01
app.command("info", help="Version and environment information.")(info.run)
app.command("doctor", help="Check the installed media stack and report what it supports.")(
    doctor.run
)
app.command("probe", help="Show input metadata and compatibility. Lands in Phase 2.")(probe.run)
app.command("split", help="Plan or run a split into capped clips. Lands in Phase 3.")(split.run)
app.command("batch", help="Split many videos in one run. Lands in Phase 12.")(batch.run)
app.command("queue", help="List, pause, and order jobs. Lands in Phase 12.")(queue.run)
app.command("status", help="Show job and clip states. Lands in Phase 8.")(status.run)
app.command("resume", help="Continue an interrupted job. Lands in Phase 9.")(resume.run)
app.command("retry", help="Re-run failed or review clips. Lands in Phase 11.")(retry.run)
app.command("reprocess", help="Re-encode selected clips. Lands in Phase 11.")(reprocess.run)
app.command("verify", help="Check a finished job against disk. Lands in Phase 11.")(verify.run)
app.command("cancel", help="Cancel a paused or interrupted job. Lands in Phase 11.")(cancel.run)
app.command("report", help="Print or export a job report. Lands in Phase 11.")(report.run)
app.command("config", help="Show and validate configuration. Lands in Phase 11.")(config.run)
app.command(
    "benchmark",
    help="Measure profiles and thread counts on this machine. Lands in Phase 13.",
)(benchmark.run)
app.command("clean", help="Remove orphan .part files. Lands in Phase 11.")(clean.run)

# Uncaught per-clip outcomes mean the run ended with issues, not that it crashed
_EXIT_CODES: tuple[tuple[type[ClipForgeError], int], ...] = (
    (UsageError, ExitCode.USAGE.value),
    (DependencyError, ExitCode.DEPENDENCY_MISSING.value),
    (PermanentClipError, ExitCode.COMPLETED_WITH_ISSUES.value),
    (OversizeResult, ExitCode.COMPLETED_WITH_ISSUES.value),
    (QualityGateFail, ExitCode.COMPLETED_WITH_ISSUES.value),
    (TransientFault, ExitCode.FATAL.value),
    (FatalJobError, ExitCode.FATAL.value),
)


def _exit_code_for(error: ClipForgeError) -> int:
    for cls, code in _EXIT_CODES:
        if isinstance(error, cls):
            return code
    return ExitCode.FATAL.value


def _render_error(error: ClipForgeError) -> None:
    typer.echo(f"error: {error.what}", err=True)
    if error.meaning:
        typer.echo(error.meaning, err=True)
    if error.fix:
        typer.echo(f"fix: {error.fix}", err=True)


def run() -> None:
    """Console script entry point: run the app, render errors, map exit codes."""
    try:
        app()
    except ClipForgeError as error:
        _render_error(error)
        raise SystemExit(_exit_code_for(error)) from None
    except KeyboardInterrupt:
        typer.echo("interrupted", err=True)
        raise SystemExit(ExitCode.INTERRUPTED.value) from None
