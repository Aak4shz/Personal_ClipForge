"""Fingerprint hashing: size plus SHA-256 of first/middle/last 1 MiB.

Used to detect whether an on-disk file is the same logical clip that the
database recorded, without re-reading the whole file.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

_CHUNK = 1 * 1024 * 1024  # 1 MiB


def fingerprint(path: Path) -> dict[str, int | str]:
    """Return a fingerprint dict for the file at path.

    Keys: size_bytes, sha256 (hex of first/middle/last 1 MiB chunks).
    Files smaller than 3 MiB hash their whole contents.
    """
    size = path.stat().st_size
    h = hashlib.sha256()

    with open(path, "rb") as f:
        if size <= 3 * _CHUNK:
            # Small file: hash the whole thing
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        else:
            # First 1 MiB
            h.update(f.read(_CHUNK))
            # Middle 1 MiB
            mid = size // 2 - _CHUNK // 2
            f.seek(mid)
            h.update(f.read(_CHUNK))
            # Last 1 MiB
            f.seek(size - _CHUNK)
            h.update(f.read(_CHUNK))

    return {"size_bytes": size, "sha256": h.hexdigest()}
