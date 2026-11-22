"""Integration tests for FFmpeg execution runner and clip verification (FR-ENC-01..07, RULE-02)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from clipforge.encoding.builder import build_encode_command
from clipforge.encoding.runner import run_encode
from clipforge.encoding.verify import verify_clip


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not installed")
def test_real_encode_and_verify(tmp_path: Path) -> None:
    # 1. Create a 1.0 second test video
    input_file = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=1:size=320x240:rate=15",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(input_file),
        ],
        capture_output=True,
        check=True,
    )

    part_file = tmp_path / "clip_0000.webm.part"
    final_file = tmp_path / "clip_0000.webm"

    # 2. Build FFmpeg command for fast profile
    cmd = build_encode_command(
        input_path=input_file,
        output_part_path=part_file,
        start_us=0,
        duration_us=1_000_000,
        video_bps=1_000_000,
        audio_bps=64_000,
        width=320,
        height=240,
        fps=15.0,
        profile="fast",
        threads=2,
    )

    # 3. Supervised run
    result = run_encode(
        cmd=cmd,
        output_part_path=part_file,
        clip_duration_seconds=1.0,
        timeout=30.0,
    )

    assert result.success is True
    assert result.exit_code == 0
    assert part_file.exists()
    assert result.size_bytes > 0

    # 4. Atomic rename .part -> .webm
    part_file.rename(final_file)
    assert final_file.exists()

    # 5. Verification
    verification = verify_clip(final_file, expected_duration=1.0)
    assert verification.valid is True
    assert verification.is_oversize is False
    assert verification.video_codec == "vp9"
    assert verification.audio_codec == "opus"
    assert len(verification.errors) == 0
