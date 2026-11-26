"""File locks and duplicate-detection (Phase 9, FR-RES-05, FR-RES-06, RULE-26).

One ``flock`` per output folder makes a second process on the same job fail
fast instead of racing on the database. Duplicate detection compares input
fingerprint + output folder + config snapshot and prompts resume / new /
cancel.
"""

from __future__ import annotations

import fcntl
import os
from pathlib import Path
from types import TracebackType


class JobLock:
    """Exclusive lock on an output folder, held for the life of a job run.

    Acquire with ``with JobLock(output_dir) as lock:``. A second process
    trying the same folder blocks until the first releases, then fails fast
    if the job is still active.
    """

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir
        self.lock_path = output_dir / ".clipforge.lock"
        self._fd: int | None = None

    def __enter__(self) -> JobLock:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(self._fd)
            self._fd = None
            raise JobLockedError(
                f"job already running on {self.output_dir}",
                meaning="another clipforge process holds the lock for this output folder",
                fix="wait for that run to finish, then run again",
            ) from None
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None


class JobLockedError(Exception):
    """Raised when a second process tries to run on a locked output folder."""

    def __init__(self, message: str, meaning: str = "", fix: str = "") -> None:
        super().__init__(message)
        self.meaning = meaning
        self.fix = fix


def duplicate_detected(db_path: Path, input_path: Path, output_dir: Path) -> tuple[int, str] | None:
    """Return (job_id, state) for an existing job on the same input+output, or None.

    Used by the resume command to decide between resume, new, and cancel.
    The fingerprint itself (input bytes) is compared by the caller.
    """
    from clipforge.storage.repo import job_exists

    return job_exists(db_path, input_path, output_dir)
