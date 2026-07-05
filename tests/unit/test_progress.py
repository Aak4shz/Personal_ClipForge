"""Unit tests for FFmpeg progress stream parsing (ARCHITECTURE.md 4.5)."""

from __future__ import annotations

from clipforge.encoding.progress import parse_progress_chunk


def test_parse_progress_chunk_valid() -> None:
    lines = [
        "frame=150\n",
        "fps=30.0\n",
        "stream_0_0_q=32.0\n",
        "bitrate=3120.5kbits/s\n",
        "total_size=1950000\n",
        "out_time_us=5000000\n",
        "out_time_ms=5000000\n",
        "out_time=00:00:05.000000\n",
        "dup_frames=0\n",
        "drop_frames=0\n",
        "speed=1.45x\n",
        "progress=continue\n",
    ]
    frame = parse_progress_chunk(lines)
    assert frame is not None
    assert frame.frame == 150
    assert frame.fps == 30.0
    assert frame.bitrate_kbps == 3120.5
    assert frame.total_size_bytes == 1950000
    assert frame.out_time_us == 5000000
    assert frame.out_time_seconds == 5.0
    assert frame.speed == 1.45
    assert not frame.is_end


def test_parse_progress_chunk_end() -> None:
    lines = [
        "frame=300",
        "fps=28.5",
        "bitrate=3123.6kbits/s",
        "total_size=3904589",
        "out_time_us=10000000",
        "speed=1.2x",
        "progress=end",
    ]
    frame = parse_progress_chunk(lines)
    assert frame is not None
    assert frame.is_end is True
    assert frame.out_time_seconds == 10.0


def test_parse_progress_chunk_empty_or_malformed() -> None:
    assert parse_progress_chunk([]) is None
    assert parse_progress_chunk(["   ", "just random text without equal sign"]) is None

    # Partial lines
    frame = parse_progress_chunk(["frame=abc", "fps=N/A", "speed=N/A"])
    assert frame is not None
    assert frame.frame == 0
    assert frame.fps == 0.0
    assert frame.speed == 0.0
