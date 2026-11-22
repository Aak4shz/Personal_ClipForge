"""Integration tests for Phase 5 MVP full run (SM-4, FR-ENC-05, FR-OPT-01, RULE-08, RULE-22)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.exit_codes import ExitCode
from clipforge.cli.main import app
from clipforge.core.constants import MAX_CLIP_SIZE_BYTES
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
def ten_minute_fixture(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 10-minute (600 s) 1080p synthetic fixture."""
    tmp = tmp_path_factory.mktemp("mvp_fixtures")
    video_path = tmp / "ten_minute_mvp.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1920x1080:r=1:d=600",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo:d=600",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "40",
            "-c:a",
            "aac",
            "-t",
            "600",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )
    return video_path


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_mvp_split_sixty_clips_full_run(ten_minute_fixture: Path, tmp_path: Path) -> None:
    """A 10-minute fixture produces 60 playable, verified clips within the 4 MiB limit (SM-4)."""
    out_dir = tmp_path / "mvp_output"
    result = runner.invoke(
        app,
        [
            "split",
            str(ten_minute_fixture),
            "-o",
            str(out_dir),
            "--profile",
            "fast",
            "--threads",
            "4",
        ],
    )

    assert result.exit_code == ExitCode.SUCCESS.value, (
        f"split failed with code {result.exit_code}:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )

    # Verify 60 clips generated
    clips = sorted(out_dir.glob("clip_*.webm"))
    assert len(clips) == 60, f"Expected 60 clips, found {len(clips)}"

    # Check 4-digit sorted naming: clip_0001.webm to clip_0060.webm
    assert clips[0].name == "clip_0001.webm"
    assert clips[-1].name == "clip_0060.webm"

    # Verify every clip adheres to format, codecs, and the hard 4 MiB limit
    for clip in clips:
        v = verify_clip(clip, max_size_bytes=MAX_CLIP_SIZE_BYTES, expected_duration=10.0)
        assert v.valid is True, f"Clip {clip.name} verification failed: {v.errors}"
        assert v.is_oversize is False, f"Clip {clip.name} is oversize ({v.size_bytes:,} bytes)"
        assert v.size_bytes <= MAX_CLIP_SIZE_BYTES
        assert v.video_codec == "vp9"
        assert v.audio_codec == "opus"

    # Ensure no temporary leftovers remain
    tmp_dir = out_dir / ".clipforge_tmp"
    assert not tmp_dir.exists() or not any(tmp_dir.iterdir())


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_mvp_oversize_never_published_on_exhaustion(tmp_path: Path) -> None:
    """Oversize exhaustion ends in failure and never publishes an oversize file (RULE-22, 46)."""
    # 1. Generate 1s test video
    input_file = tmp_path / "short_src.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=1:size=320x240:rate=15",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(input_file),
        ],
        capture_output=True,
        check=True,
    )

    out_dir = tmp_path / "oversize_test_out"
    # Set an impossibly small max-size (100 bytes)
    result = runner.invoke(
        app,
        [
            "split",
            str(input_file),
            "-o",
            str(out_dir),
            "--max-size",
            "100",
            "--profile",
            "fast",
        ],
    )

    # Must exit with failure (code 4 for fatal / 0 completed)
    assert result.exit_code == ExitCode.FATAL.value

    # RULE-22 & RULE-46: No oversize file may ever be published as completed
    published_clip = out_dir / "clip_0001.webm"
    assert not published_clip.exists()
