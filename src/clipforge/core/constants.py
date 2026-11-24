"""The non-negotiable numbers and names of the project.

RULE-15 makes the counter caps law: changing one is a blueprint change, not a
code change. Config defaults in core/config.py reference these values, so
there is one source of truth for every number that shapes a job.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum

MIB = 1_048_576

# Size enforcement: the hard ceiling and the internal working target.
# The target is rounded up, so it can never exceed the hard ceiling.
MAX_CLIP_SIZE_BYTES = 4 * MIB
SAFETY_MARGIN_PERCENT = 5
TARGET_CLIP_SIZE_BYTES = -(-MAX_CLIP_SIZE_BYTES * (100 - SAFETY_MARGIN_PERCENT) // 100)

# Counter caps (RULE-15): 1 initial attempt plus at most the retries below,
# never more than MAX_TOTAL_ENCODES FFmpeg runs for one clip.
MAX_SIZE_ATTEMPTS = 4
MAX_FAULT_RETRIES = 3
MAX_TOTAL_ENCODES = 8

# Delay schedule between fault retries, in seconds
RETRY_DELAYS_SECONDS: tuple[float, ...] = (2.0, 5.0, 10.0)


class ExitCode(IntEnum):
    """The six documented exit codes (FR-CLI-02, RULE-21). Scripts depend on them."""

    SUCCESS = 0
    COMPLETED_WITH_ISSUES = 1
    USAGE = 2
    DEPENDENCY_MISSING = 3
    FATAL = 4
    INTERRUPTED = 130


class JobState(StrEnum):
    """Job-level states (blueprint section 12.1)."""

    PENDING = "PENDING"
    ANALYZING = "ANALYZING"
    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_ISSUES = "COMPLETED_WITH_ISSUES"
    PAUSED = "PAUSED"
    INTERRUPTED = "INTERRUPTED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class ClipState(StrEnum):
    """Clip-level states (blueprint section 12.2)."""

    PENDING = "PENDING"
    ENCODING = "ENCODING"
    VERIFYING = "VERIFYING"
    RETRYING = "RETRYING"
    COMPLETED = "COMPLETED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"
    FAILED_SIZE = "FAILED_SIZE"
    FAILED_LIMIT = "FAILED_LIMIT"
    SKIPPED = "SKIPPED"
    CANCELLED = "CANCELLED"


# A crash can hit a clip in any of these; recovery resets them to PENDING
CLIP_IN_FLIGHT_STATES: frozenset[ClipState] = frozenset(
    {ClipState.ENCODING, ClipState.VERIFYING, ClipState.RETRYING}
)

# No resume or retry can move a job out of these states
JOB_TERMINAL_STATES: frozenset[JobState] = frozenset(
    {
        JobState.COMPLETED,
        JobState.COMPLETED_WITH_ISSUES,
        JobState.CANCELLED,
        JobState.FAILED,
    }
)


# Allowed clip state transitions: current -> set of allowed next states
CLIP_TRANSITIONS: dict[ClipState, frozenset[ClipState]] = {
    ClipState.PENDING: frozenset({ClipState.ENCODING, ClipState.SKIPPED, ClipState.CANCELLED}),
    ClipState.ENCODING: frozenset({
        ClipState.VERIFYING,
        ClipState.RETRYING,
        ClipState.FAILED,
        ClipState.FAILED_SIZE,
        ClipState.FAILED_LIMIT,
        ClipState.CANCELLED,
    }),
    ClipState.VERIFYING: frozenset({
        ClipState.COMPLETED,
        ClipState.NEEDS_REVIEW,
        ClipState.RETRYING,
        ClipState.FAILED,
        ClipState.CANCELLED,
    }),
    ClipState.RETRYING: frozenset({
        ClipState.ENCODING,
        ClipState.FAILED,
        ClipState.FAILED_SIZE,
        ClipState.FAILED_LIMIT,
        ClipState.CANCELLED,
    }),
    ClipState.COMPLETED: frozenset(),  # terminal
    ClipState.NEEDS_REVIEW: frozenset(),  # terminal
    ClipState.FAILED: frozenset(),  # terminal
    ClipState.FAILED_SIZE: frozenset(),  # terminal
    ClipState.FAILED_LIMIT: frozenset(),  # terminal
    ClipState.SKIPPED: frozenset(),  # terminal
    ClipState.CANCELLED: frozenset(),  # terminal
}

# Allowed job state transitions: current -> set of allowed next states
JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset({JobState.ANALYZING, JobState.QUEUED, JobState.CANCELLED}),
    JobState.ANALYZING: frozenset({
        JobState.QUEUED, JobState.PROCESSING, JobState.FAILED, JobState.CANCELLED,
    }),
    JobState.QUEUED: frozenset({JobState.PROCESSING, JobState.PAUSED, JobState.CANCELLED}),
    JobState.PROCESSING: frozenset({
        JobState.COMPLETED,
        JobState.COMPLETED_WITH_ISSUES,
        JobState.FAILED,
        JobState.INTERRUPTED,
        JobState.PAUSED,
    }),
    JobState.COMPLETED: frozenset(),  # terminal
    JobState.COMPLETED_WITH_ISSUES: frozenset(),  # terminal
    JobState.PAUSED: frozenset({JobState.PROCESSING, JobState.CANCELLED}),
    JobState.INTERRUPTED: frozenset({JobState.PROCESSING, JobState.CANCELLED}),
    JobState.CANCELLED: frozenset(),  # terminal
    JobState.FAILED: frozenset(),  # terminal
}


def validate_clip_transition(
    current: ClipState, next_state: ClipState
) -> None:
    """Raise ValueError if a clip cannot transition from ``current`` to ``next_state``.

    Illegal transitions are a programming error, not a runtime condition —
    catching them early prevents corrupt state from reaching the database.
    """
    allowed = CLIP_TRANSITIONS.get(current, frozenset())
    if next_state not in allowed:
        raise ValueError(
            f"illegal clip state transition: {current.value} -> {next_state.value}"
        )


def validate_job_transition(current: JobState, next_state: JobState) -> None:
    """Raise ValueError if a job cannot transition from ``current`` to ``next_state``."""
    allowed = JOB_TRANSITIONS.get(current, frozenset())
    if next_state not in allowed:
        raise ValueError(
            f"illegal job state transition: {current.value} -> {next_state.value}"
        )


def is_clip_terminal(state: ClipState) -> bool:
    """Return True when a clip state is terminal (no further transitions)."""
    return not CLIP_TRANSITIONS.get(state)


def is_job_terminal(state: JobState) -> bool:
    """Return True when a job state is terminal."""
    return not JOB_TRANSITIONS.get(state)


def is_clip_in_flight(state: ClipState) -> bool:
    """Return True when a crash could leave a clip in this state."""
    return state in CLIP_IN_FLIGHT_STATES


def is_job_terminal_state(state: JobState) -> bool:
    """Return True when no resume or retry can move a job out of this state."""
    return state in JOB_TERMINAL_STATES
