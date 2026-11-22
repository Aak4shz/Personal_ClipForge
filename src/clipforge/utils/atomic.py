"""Atomic file publishing via fsync and os.replace (RULE-08, FR-RES-05)."""

from __future__ import annotations

import os
from pathlib import Path


def atomic_publish(src_path: Path, dst_path: Path) -> None:
    """Publish a completed file atomically by flushing, fsyncing, and replacing.

    Args:
        src_path: Path to the source file (e.g. .part file).
        dst_path: Path to the target published file.

    Raises:
        FileNotFoundError: If src_path does not exist.
        OSError: If an operating system error occurs during fsync or replace.
    """
    if not src_path.exists():
        raise FileNotFoundError(f"source file for atomic publish does not exist: {src_path}")

    dst_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Flush and fsync file data to disk
    with open(src_path, "r+b") as f:
        f.flush()
        os.fsync(f.fileno())

    # 2. Atomic rename on the same filesystem
    os.replace(src_path, dst_path)

    # 3. Fsync target parent directory for directory entry durability
    if hasattr(os, "O_DIRECTORY"):
        try:
            dir_fd = os.open(dst_path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
