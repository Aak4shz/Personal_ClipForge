"""XDG-aware location resolvers (NFR-09).

ARCHITECTURE.md 4.1 allows core/ to import from utils/, which is why these
live here instead of inside a module above core. Each resolver honors its
environment variable when it names an absolute path, and falls back to the
XDG default otherwise, per the XDG base directory specification.
"""

from __future__ import annotations

import os
from pathlib import Path


def _xdg_dir(env_var: str, default: Path) -> Path:
    """Return an XDG base directory: the env var when absolute, the default otherwise."""
    value = os.environ.get(env_var, "").strip()
    if value and os.path.isabs(value):
        return Path(value)
    return default


def config_home() -> Path:
    """Return $XDG_CONFIG_HOME or ~/.config."""
    return _xdg_dir("XDG_CONFIG_HOME", Path.home() / ".config")


def data_home() -> Path:
    """Return $XDG_DATA_HOME or ~/.local/share."""
    return _xdg_dir("XDG_DATA_HOME", Path.home() / ".local/share")


def state_home() -> Path:
    """Return $XDG_STATE_HOME or ~/.local/state."""
    return _xdg_dir("XDG_STATE_HOME", Path.home() / ".local/state")
