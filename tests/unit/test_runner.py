"""Unit tests for supervised process execution and kill ladder (ARCHITECTURE.md 4.5, 12)."""

from __future__ import annotations

import sys
from pathlib import Path

from clipforge.encoding.progress import ProgressFrame
from clipforge.encoding.runner import _extract_stderr_tail, run_encode


def test_extract_stderr_tail() -> None:
    assert _extract_stderr_tail("") == ""

    # Many lines
    lines = [f"line {i}" for i in range(100)]
    tail = _extract_stderr_tail("\n".join(lines), max_lines=5)
    assert tail.splitlines() == ["line 95", "line 96", "line 97", "line 98", "line 99"]

    # Long text truncation
    long_tail = _extract_stderr_tail("a" * 5000, max_chars=100)
    assert len(long_tail) == 100


def test_run_encode_success(tmp_path: Path) -> None:
    part_path = tmp_path / "test.webm.part"

    # Command that prints progress and creates the file
    script = (
        f"import sys\n"
        f"with open('{part_path}', 'wb') as f: f.write(b'data')\n"
        f"print('frame=10\\nprogress=continue', flush=True)\n"
    )
    cmd = [sys.executable, "-c", script]

    frames: list[ProgressFrame] = []
    res = run_encode(
        cmd=cmd,
        output_part_path=part_path,
        clip_duration_seconds=1.0,
        timeout=5.0,
        on_progress=frames.append,
    )

    assert res.success is True
    assert res.exit_code == 0
    assert not res.is_timeout
    assert res.size_bytes == 4
    assert len(frames) == 1
    assert frames[0].frame == 10
    assert part_path.exists()


def test_run_encode_failure_cleans_up_part(tmp_path: Path) -> None:
    part_path = tmp_path / "failed.webm.part"

    # Script that writes a partial file and exits with error code 1
    script = (
        f"with open('{part_path}', 'wb') as f: f.write(b'partial')\n"
        f"import sys; sys.stderr.write('Something broke!\\n'); sys.exit(1)\n"
    )
    cmd = [sys.executable, "-c", script]

    res = run_encode(
        cmd=cmd,
        output_part_path=part_path,
        clip_duration_seconds=1.0,
        timeout=5.0,
    )

    assert res.success is False
    assert res.exit_code == 1
    assert not res.is_timeout
    assert not part_path.exists()  # Cleaned up!
    assert "Something broke!" in res.stderr_tail


def test_run_encode_watchdog_timeout(tmp_path: Path) -> None:
    part_path = tmp_path / "timeout.webm.part"

    # Script that hangs and creates a partial file
    script = (
        f"import time\nwith open('{part_path}', 'wb') as f: f.write(b'hanging')\ntime.sleep(10)\n"
    )
    cmd = [sys.executable, "-c", script]

    res = run_encode(
        cmd=cmd,
        output_part_path=part_path,
        clip_duration_seconds=0.1,
        timeout=0.5,  # Short timeout to trigger watchdog kill ladder
    )

    assert res.success is False
    assert res.is_timeout is True
    assert not part_path.exists()  # Cleaned up on timeout!
