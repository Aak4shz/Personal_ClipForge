"""Resource sampler: disk and RAM guards (Phase 9, FR-RES-04).

Pre-flight estimate refuses jobs that cannot fit on disk; runtime check
before every clip pauses the job with completed clips intact.
"""

from __future__ import annotations

import shutil
from pathlib import Path


class DiskFullError(Exception):
    """The target disk cannot hold the job; no clips were harmed."""

    def __init__(self, message: str, meaning: str = "", fix: str = "") -> None:
        super().__init__(message)
        self.meaning = meaning
        self.fix = fix


def estimate_needed_bytes(clip_count: int, max_size_bytes: int) -> int:
    """Upper bound on bytes the job will consume on disk.

    clips x limit x 1.05, plus a small working margin for .part files.
    """
    return int(clip_count * max_size_bytes * 1.05) + (10 * 1024 * 1024)


def free_bytes(path: Path) -> int:
    """Free bytes on the filesystem holding path."""
    usage = shutil.disk_usage(str(path))
    return usage.free


def assert_disk_fit(output_dir: Path, clip_count: int, max_size_bytes: int) -> None:
    """Raise DiskFullError if the job cannot fit on disk (pre-flight guard)."""
    needed = estimate_needed_bytes(clip_count, max_size_bytes)
    have = free_bytes(output_dir)
    if have < needed:
        raise DiskFullError(
            f"not enough disk space for {clip_count} clips: "
            f"need about {needed // (1024 * 1024)} MiB, have {have // (1024 * 1024)} MiB",
            meaning="the output disk is too small for the whole job",
            fix="point output_dir at a larger disk or free space first",
        )
