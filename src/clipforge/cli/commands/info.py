"""The ``info`` command: version and environment facts."""

from __future__ import annotations

import platform
import sys

import typer

from clipforge import __version__


def run() -> None:
    """Print the ClipForge version, the Python version, and the platform."""
    typer.echo(f"clipforge {__version__}")
    typer.echo(f"python {platform.python_version()} ({sys.executable})")
    typer.echo(f"platform {platform.platform()}")
