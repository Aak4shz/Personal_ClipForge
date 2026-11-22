"""Integration tests for `clipforge split --dry-run` (Phase 3)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.exit_codes import ExitCode
from clipforge.cli.main import app

runner = CliRunner()


def _has_ffmpeg_and_ffprobe() -> bool:
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.fixture(scope="module")
def ten_minute_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a fast 10-minute (600 s) 1080p video fixture using ffmpeg."""
    tmp = tmp_path_factory.mktemp("split_fixtures")
    video_path = tmp / "ten_minute.mp4"
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


@pytest.fixture(scope="module")
def six_hundred_point_two_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a 600.2 s video fixture for orphan tail testing."""
    tmp = tmp_path_factory.mktemp("split_tail_fixtures")
    video_path = tmp / "tail_test.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1920x1080:r=1:d=600.2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo:d=600.2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "40",
            "-c:a",
            "aac",
            "-t",
            "600.2",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )
    return video_path


@pytest.fixture(scope="module")
def four_k_sixty_video(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Generate a short 4K 60fps video fixture for risky feasibility testing."""
    tmp = tmp_path_factory.mktemp("split_4k_fixtures")
    video_path = tmp / "four_k_60.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=3840x2160:r=60:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo:d=1",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-t",
            "1",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )
    return video_path


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_split_dry_run_ten_minute_video(ten_minute_video: Path) -> None:
    """Split dry-run on a 10-minute fixture reports 60 clips and comfortable verdict."""
    result = runner.invoke(app, ["split", "--dry-run", str(ten_minute_video)])
    assert result.exit_code == ExitCode.SUCCESS.value, (
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    out = result.stdout
    assert "60 clips" in out
    assert "COMFORTABLE" in out
    assert "3,123,671 bps" in out
    assert "80,000 B" in out
    assert "00:10:00.000000" in out


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_split_dry_run_six_hundred_point_two_seconds(six_hundred_point_two_video: Path) -> None:
    """A 600.2 s video under merge_into_previous must not plan an orphan clip."""
    # Under merge_into_previous: exactly 60 clips
    res_merge = runner.invoke(
        app,
        ["split", "--dry-run", "--tail", "merge_into_previous", str(six_hundred_point_two_video)],
    )
    assert res_merge.exit_code == ExitCode.SUCCESS.value
    assert "60 clips" in res_merge.stdout
    assert "merged" in res_merge.stdout

    # Under drop: exactly 60 clips
    res_drop = runner.invoke(
        app,
        ["split", "--dry-run", "--tail", "drop", str(six_hundred_point_two_video)],
    )
    assert res_drop.exit_code == ExitCode.SUCCESS.value
    assert "60 clips" in res_drop.stdout
    assert "dropped" in res_drop.stdout

    # Under keep: 61 clips
    res_keep = runner.invoke(
        app,
        ["split", "--dry-run", "--tail", "keep", str(six_hundred_point_two_video)],
    )
    assert res_keep.exit_code == ExitCode.SUCCESS.value
    assert "61 clips" in res_keep.stdout
    assert "kept" in res_keep.stdout


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_split_dry_run_risky_feasibility(four_k_sixty_video: Path) -> None:
    """4K 60fps video reports RISKY feasibility verdict."""
    result = runner.invoke(app, ["split", "--dry-run", str(four_k_sixty_video)])
    assert result.exit_code == ExitCode.SUCCESS.value
    assert "RISKY" in result.stdout


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_split_dry_run_range_constraints(ten_minute_video: Path) -> None:
    """Boundaries hold across a non-zero source start time offset (--start and --end)."""
    result = runner.invoke(
        app,
        [
            "split",
            "--dry-run",
            "--start",
            "00:01:00",
            "--end",
            "00:02:00",
            str(ten_minute_video),
        ],
    )
    assert result.exit_code == ExitCode.SUCCESS.value
    out = result.stdout
    assert "6 clips" in out
    assert "00:01:00.000000" in out
    assert "00:02:00.000000" in out


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_split_dry_run_json_output(ten_minute_video: Path) -> None:
    """--json output produces valid parseable JSON with full structure."""
    result = runner.invoke(app, ["split", "--dry-run", "--json", str(ten_minute_video)])
    assert result.exit_code == ExitCode.SUCCESS.value

    data = json.loads(result.stdout)
    assert data["clip_count"] == 60
    assert data["budget"]["video_bps"] == 3123671
    assert data["budget"]["audio_bytes"] == 80000
    assert data["feasibility"]["verdict"] == "comfortable"
    assert len(data["boundaries"]) == 60
    assert data["boundaries"][0]["start_us"] == 0
    assert data["boundaries"][0]["end_us"] == 10000000
    assert data["boundaries"][-1]["end_us"] == 600000000


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_split_invalid_profile_exits_two(ten_minute_video: Path) -> None:
    """Running split with an invalid profile exits with code 2."""
    result = runner.invoke(app, ["split", "--profile", "invalid_prof", str(ten_minute_video)])
    assert result.exit_code == ExitCode.USAGE.value
    assert "invalid profile" in result.stderr


@pytest.mark.skipif(not _has_ffmpeg_and_ffprobe(), reason="ffmpeg/ffprobe not available")
def test_split_nonexistent_file_rejected(tmp_path: Path) -> None:
    """Non-existent file raises UsageError with exit code 2."""
    missing = tmp_path / "does_not_exist.mp4"
    result = runner.invoke(app, ["split", "--dry-run", str(missing)])
    assert result.exit_code == ExitCode.USAGE.value
    assert "input file not found" in result.stderr
