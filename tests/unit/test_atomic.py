"""Unit tests for atomic publish helper (RULE-08, FR-RES-05)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clipforge.utils.atomic import atomic_publish


def test_atomic_publish_success(tmp_path: Path) -> None:
    src = tmp_path / "test.webm.part"
    dst = tmp_path / "test.webm"
    data = b"video-stream-bytes-12345"

    src.write_bytes(data)
    atomic_publish(src, dst)

    assert not src.exists()
    assert dst.exists()
    assert dst.read_bytes() == data


def test_atomic_publish_overwrite_existing(tmp_path: Path) -> None:
    src = tmp_path / "clip.webm.part"
    dst = tmp_path / "clip.webm"

    dst.write_bytes(b"old-content")
    src.write_bytes(b"new-content")

    atomic_publish(src, dst)

    assert not src.exists()
    assert dst.exists()
    assert dst.read_bytes() == b"new-content"


def test_atomic_publish_creates_parent_directories(tmp_path: Path) -> None:
    src = tmp_path / "test.part"
    dst = tmp_path / "subdir" / "nested" / "final.webm"

    src.write_bytes(b"nested-content")
    atomic_publish(src, dst)

    assert not src.exists()
    assert dst.exists()
    assert dst.read_bytes() == b"nested-content"


def test_atomic_publish_missing_source_raises(tmp_path: Path) -> None:
    src = tmp_path / "missing.part"
    dst = tmp_path / "out.webm"

    with pytest.raises(FileNotFoundError, match="does not exist"):
        atomic_publish(src, dst)
