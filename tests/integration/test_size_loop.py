"""Integration tests for smart size control and two-pass rate control (FR-OPT-05..07, RULE-15)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.exit_codes import ExitCode
from clipforge.cli.main import app
from clipforge.encoding.verify import verify_clip

runner = CliRunner()


def _has_ffmpeg_and_ffprobe() -> bool:
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 2-second synthetic video fixture with motion."""
    tmp = tmp_path_factory.mktemp("size_loop_fixtures")
    video_path = tmp / "motion_sample.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=2:size=320x240:rate=15",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo:d=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )
    return video_path


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_size_loop_converges_within_limit(sample_video: Path, tmp_path: Path) -> None:
    """A clip with a tight budget converges within limit via size loop (FR-OPT-05, FR-OPT-06)."""
    out_dir = tmp_path / "converge_out"
    # Budget of 30 KB
    max_size = 30_000

    result = runner.invoke(
        app,
        [
            "split",
            str(sample_video),
            "-o",
            str(out_dir),
            "--max-size",
            str(max_size),
            "--profile",
            "fast",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS.value, (
        f"split failed with code {result.exit_code}:\nstdout: {result.stdout}"
    )

    clip = out_dir / "clip_0001.webm"
    assert clip.exists(), "Expected published clip_0001.webm"

    # Verify validity and size ceiling
    v = verify_clip(clip, max_size_bytes=max_size, expected_duration=2.0)
    assert v.valid is True
    assert v.size_bytes <= max_size
    assert v.video_codec == "vp9"

    # Verify temporary directory and passlogs are cleaned up
    tmp_dir = out_dir / ".clipforge_tmp"
    assert not tmp_dir.exists() or not any(tmp_dir.iterdir())


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_size_loop_exhaustion_honest_failure(sample_video: Path, tmp_path: Path) -> None:
    """An impossible limit exhausts 4 attempts, exits fatal, publishes nothing (RULE-15)."""
    out_dir = tmp_path / "exhaust_out"
    # 500 bytes is smaller than any WebM container header
    impossible_size = 500

    result = runner.invoke(
        app,
        [
            "split",
            str(sample_video),
            "-o",
            str(out_dir),
            "--max-size",
            str(impossible_size),
            "--profile",
            "fast",
        ],
    )

    assert result.exit_code == ExitCode.FATAL.value
    assert "FAILED_SIZE" in result.stdout
    assert "after 4" in result.stdout

    # Never publishes an oversize file
    assert not (out_dir / "clip_0001.webm").exists()
    # Temporary files cleaned up
    tmp_dir = out_dir / ".clipforge_tmp"
    assert not tmp_dir.exists() or not any(tmp_dir.iterdir())
