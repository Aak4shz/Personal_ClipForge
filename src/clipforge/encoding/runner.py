"""Supervised FFmpeg process runner with watchdog and kill ladder (ARCHITECTURE.md 4.5, 12)."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from clipforge.encoding.progress import ProgressFrame, parse_progress_chunk


@dataclass(frozen=True)
class EncodeResult:
    """Structured result of one supervised FFmpeg encode."""

    output_path: Path
    exit_code: int
    success: bool
    size_bytes: int
    duration_seconds: float
    stderr_tail: str
    is_timeout: bool = False
    last_progress: ProgressFrame | None = None


def _extract_stderr_tail(raw_stderr: str, max_lines: int = 50, max_chars: int = 4096) -> str:
    """Keep bounded tail of stderr output for error classification."""
    if not raw_stderr:
        return ""
    lines = raw_stderr.strip().splitlines()
    tail_lines = lines[-max_lines:] if len(lines) > max_lines else lines
    tail_text = "\n".join(tail_lines)
    if len(tail_text) > max_chars:
        return tail_text[-max_chars:]
    return tail_text


def _kill_process_group(proc: subprocess.Popen[str], sig: int) -> None:
    """Send signal to entire process group or fall back to process."""
    try:
        os.killpg(os.getpgid(proc.pid), sig)
    except (ProcessLookupError, OSError, AttributeError):
        try:
            if sig == signal.SIGKILL:
                proc.kill()
            else:
                proc.terminate()
        except (ProcessLookupError, OSError):
            pass


def run_encode(
    cmd: list[str],
    output_part_path: Path,
    clip_duration_seconds: float = 10.0,
    timeout_factor: float = 20.0,
    timeout: float | None = None,
    on_progress: Callable[[ProgressFrame], None] | None = None,
    is_analysis_pass: bool = False,
) -> EncodeResult:
    """Execute FFmpeg command under watchdog supervision with kill ladder.

    Args:
        cmd: FFmpeg command argument list.
        output_part_path: Path to target .part output file.
        clip_duration_seconds: Duration of clip being encoded.
        timeout_factor: Factor for watchdog timeout = max(60s, duration * factor).
        timeout: Explicit timeout in seconds (overrides timeout_factor if given).
        on_progress: Optional callback invoked whenever a progress frame is parsed.
        is_analysis_pass: If True, command writes to null and does not produce output_part_path.

    Returns:
        Structured EncodeResult. If encode fails or times out, output .part file is removed.
    """
    effective_timeout = (
        timeout if timeout is not None else max(60.0, clip_duration_seconds * timeout_factor)
    )

    # Ensure parent directory for .part file exists
    if not is_analysis_pass:
        output_part_path.parent.mkdir(parents=True, exist_ok=True)

    start_time = time.monotonic()
    is_timeout = False
    last_frames: list[ProgressFrame] = []
    stderr_chunks: list[str] = []

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        start_new_session=True,
    )

    def _read_stdout() -> None:
        if proc.stdout is None:
            return
        chunk: list[str] = []
        for line in iter(proc.stdout.readline, ""):
            chunk.append(line)
            if line.startswith("progress="):
                frame = parse_progress_chunk(chunk)
                if frame:
                    last_frames.append(frame)
                    if on_progress:
                        on_progress(frame)
                chunk = []

    def _read_stderr() -> None:
        if proc.stderr is None:
            return
        for line in iter(proc.stderr.readline, ""):
            stderr_chunks.append(line)

    t_out = threading.Thread(target=_read_stdout, daemon=True)
    t_err = threading.Thread(target=_read_stderr, daemon=True)
    t_out.start()
    t_err.start()

    try:
        proc.wait(timeout=effective_timeout)
    except subprocess.TimeoutExpired:
        is_timeout = True
        # Kill ladder step 1: SIGTERM to process group, wait up to 5s
        _kill_process_group(proc, signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            # Kill ladder step 2: SIGKILL after 5s
            _kill_process_group(proc, signal.SIGKILL)
            proc.wait()

    t_out.join(timeout=1.0)
    t_err.join(timeout=1.0)

    duration = time.monotonic() - start_time
    raw_stderr = "".join(stderr_chunks)
    stderr_tail = _extract_stderr_tail(raw_stderr)
    exit_code = proc.returncode if proc.returncode is not None else -1

    last_prog = last_frames[-1] if last_frames else None

    # Check output file status
    if is_analysis_pass:
        size_bytes = 0
        success = (exit_code == 0) and not is_timeout
    else:
        file_exists = output_part_path.exists()
        size_bytes = output_part_path.stat().st_size if file_exists else 0
        success = (exit_code == 0) and not is_timeout and file_exists and (size_bytes > 0)

        # Clean up .part file on any failure (ARCHITECTURE.md 4.5)
        if not success and file_exists:
            output_part_path.unlink(missing_ok=True)
            size_bytes = 0

    return EncodeResult(
        output_path=output_part_path,
        exit_code=exit_code,
        success=success,
        size_bytes=size_bytes,
        duration_seconds=duration,
        stderr_tail=stderr_tail,
        is_timeout=is_timeout,
        last_progress=last_prog,
    )
