"""Atomic manifest.json writer: write temp, fsync, os.replace, after every clip.

The manifest is a portable mirror of the database for each output folder,
updated after every clip finishes (RULE-08 style atomicity).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import cast


def write_manifest(output_dir: Path, job_id: int, clips: list[dict[str, object]]) -> None:
    """Atomically write manifest.json into output_dir.

    Writes to a temp file in the same directory, fsyncs file data, then
    os.replace() over manifest.json, then fsyncs the parent directory.
    Never leaves a partial manifest on disk.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    tmp_path = output_dir / ".manifest.json.tmp"

    payload = {
        "job_id": job_id,
        "clip_count": len(clips),
        "clips": clips,
    }

    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp_path, manifest_path)

    # Fsync the directory entry so the rename is durable
    try:
        dir_fd = os.open(str(output_dir), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:
        pass


def read_manifest(output_dir: Path) -> dict[str, object] | None:
    """Read manifest.json from output_dir, or None if missing/invalid."""
    manifest_path = output_dir / "manifest.json"
    if not manifest_path.is_file():
        return None
    try:
        return cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return None
