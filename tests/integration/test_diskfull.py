"""Integration tests for Phase 9 disk guards (FR-RES-04).

Pre-flight estimate refuses jobs that cannot fit on disk; runtime check before
every clip pauses the job with completed clips intact.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clipforge.core.config import ClipForgeConfig
from clipforge.monitoring.sampler import (
    DiskFullError,
    assert_disk_fit,
    estimate_needed_bytes,
    free_bytes,
)


def test_estimate_needed_bytes_scales_with_clips() -> None:
    """Needed bytes grow with clip count and limit."""
    one = estimate_needed_bytes(1, 4 * 1024 * 1024)
    two = estimate_needed_bytes(2, 4 * 1024 * 1024)
    assert two > one
    assert one > 4 * 1024 * 1024  # includes the 5% overhead + margin


def test_assert_disk_fit_raises_when_too_small(tmp_path: Path) -> None:
    """assert_disk_fit raises DiskFullError when free space is below need."""
    tiny_dir = tmp_path / "tiny"
    tiny_dir.mkdir()
    have = free_bytes(tiny_dir)
    # Need far more than any real disk has (1 exbibyte) -> DiskFullError.
    with pytest.raises(DiskFullError):
        assert_disk_fit(tiny_dir, clip_count=1, max_size_bytes=have + 1)


def test_assert_disk_fit_passes_when_enough_space(tmp_path: Path) -> None:
    """assert_disk_fit passes when free space comfortably covers the need."""
    big_dir = tmp_path / "big"
    big_dir.mkdir()
    have = free_bytes(big_dir)
    # Need far less than what a real disk has.
    assert_disk_fit(big_dir, clip_count=1, max_size_bytes=1024)
    assert have > 0


def test_free_bytes_returns_positive_on_real_dir(tmp_path: Path) -> None:
    """free_bytes reports free space on a real directory."""
    d = tmp_path / "some_dir"
    d.mkdir()
    assert free_bytes(d) > 0


def test_diskfull_error_has_meaning_and_fix() -> None:
    """DiskFullError carries a meaning and a fix for the user."""
    err = DiskFullError("not enough space", meaning="small disk", fix="use a bigger disk")
    assert err.meaning == "small disk"
    assert err.fix == "use a bigger disk"


def test_config_paths_database_defaults(tmp_path: Path) -> None:
    """Config paths.database is a real Path (smoke test for config wiring)."""
    cfg = ClipForgeConfig()
    assert isinstance(cfg.paths.database, Path)
