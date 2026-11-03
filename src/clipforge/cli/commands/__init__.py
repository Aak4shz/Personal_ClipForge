"""Command modules and the helper shared by unbuilt commands."""

from __future__ import annotations

from typing import NoReturn

import typer

from clipforge.cli.exit_codes import ExitCode

_REAL_IN_PHASE_1 = ("doctor", "info")


def not_built_yet(command: str, phase: int) -> NoReturn:
    """Print the RULE-19 shape for an unbuilt command and exit 2 (Phase 1 contract)."""
    typer.echo(f"error: clipforge {command} is not built yet", err=True)
    typer.echo(
        f"it lands in Phase {phase} of Phases.md; "
        f"today the real commands are {', '.join(_REAL_IN_PHASE_1)}",
        err=True,
    )
    typer.echo(
        "fix: run `clipforge --help` to see what exists, "
        "or `clipforge doctor` to check the media stack",
        err=True,
    )
    raise typer.Exit(ExitCode.USAGE.value)
