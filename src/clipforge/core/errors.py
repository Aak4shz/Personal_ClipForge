"""The exception hierarchy (ARCHITECTURE.md 4.1).

Library code raises; the CLI layer renders and maps to exit codes (RULE-20).
Every message follows the RULE-19 shape: what happened, what it means, what
to run next.
"""

from __future__ import annotations


class ClipForgeError(Exception):
    """Base class for every error ClipForge raises on purpose.

    Attributes:
        what: One line stating the fact, naming the file or clip involved.
        meaning: What it means for the job, when that adds something.
        fix: A runnable command or a concrete action, when one exists.
    """

    def __init__(self, what: str, meaning: str = "", fix: str = "") -> None:
        super().__init__(what)
        self.what = what
        self.meaning = meaning
        self.fix = fix

    def __str__(self) -> str:
        lines = [self.what]
        if self.meaning:
            lines.append(self.meaning)
        if self.fix:
            lines.append(f"fix: {self.fix}")
        return "\n".join(lines)


class UsageError(ClipForgeError):
    """Bad invocation or configuration; the run never starts (exit 2)."""


class DependencyError(ClipForgeError):
    """A required external component is missing or unusable (exit 3)."""


class FatalJobError(ClipForgeError):
    """The job cannot continue; completed clips stay protected (exit 4)."""


class TransientFault(ClipForgeError):
    """A retriable failure, such as a killed encode or a stalled pipe."""


class PermanentClipError(ClipForgeError):
    """A clip that will never succeed, so it is never retried (RULE-14)."""


class OversizeResult(ClipForgeError):
    """An encode finished but the file is over the size ceiling.

    Attributes:
        clip_index: The clip that came out too large.
        size_bytes: The size the encode actually produced.
        limit_bytes: The hard ceiling it had to fit under.
    """

    def __init__(
        self,
        what: str,
        clip_index: int,
        size_bytes: int,
        limit_bytes: int,
        meaning: str = "",
        fix: str = "",
    ) -> None:
        super().__init__(what, meaning=meaning, fix=fix)
        self.clip_index = clip_index
        self.size_bytes = size_bytes
        self.limit_bytes = limit_bytes


class QualityGateFail(ClipForgeError):
    """A clip finished but missed its quality threshold.

    Attributes:
        clip_index: The clip that missed the threshold.
        metric: The metric that was measured, such as ssim.
        score: The measured value.
        threshold: The minimum the config demanded.
    """

    def __init__(
        self,
        what: str,
        clip_index: int,
        metric: str,
        score: float,
        threshold: float,
        meaning: str = "",
        fix: str = "",
    ) -> None:
        super().__init__(what, meaning=meaning, fix=fix)
        self.clip_index = clip_index
        self.metric = metric
        self.score = score
        self.threshold = threshold
