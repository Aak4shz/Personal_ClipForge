"""Integration tests for `clipforge probe` against real ffprobe (FR-PRO-01/02/03)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.exit_codes import ExitCode
from clipforge.cli.main import app

runner = CliRunner()


def _has_ffprobe() -> bool:
    try:
        subprocess.run(["ffprobe", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.mark.skipif(not _has_ffprobe(), reason="ffprobe not available")
def test_probe_real_video_prints_metadata_and_compatibility(tmp_path: Path) -> None:
    """Generate a lavfi test video and probe it."""
    # Create a 2-second 1080p30 test video with H.264 + AAC
    video_path = tmp_path / "test.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=2:size=1920x1080:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            "-shortest",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )

    result = runner.invoke(app, ["probe", str(video_path)])
    assert result.exit_code == ExitCode.SUCCESS.value, (
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )

    output = result.stdout
    # Metadata sections present
    assert "Container" in output
    assert "Video streams" in output
    assert "Audio streams" in output
    # Compatibility sections present
    assert "Container compatibility" in output
    assert "Video stream compatibility" in output
    assert "Audio stream compatibility" in output
    # Duration printed
    assert "Duration:" in output
    # Specific values from the generated video
    assert "1920" in output  # width
    assert "1080" in output  # height
    assert "h264" in output or "libx264" in output
    assert "aac" in output


@pytest.mark.skipif(not _has_ffprobe(), reason="ffprobe not available")
def test_probe_audio_only_is_rejected(tmp_path: Path) -> None:
    """Audio-only file should be rejected with a specific message."""
    audio_path = tmp_path / "audio_only.m4a"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=2",
            "-c:a",
            "aac",
            str(audio_path),
        ],
        capture_output=True,
        check=True,
    )

    result = runner.invoke(app, ["probe", str(audio_path)])
    assert result.exit_code == ExitCode.USAGE.value
    assert "no video stream" in result.stderr.lower() or "audio-only" in result.stderr.lower()


@pytest.mark.skipif(not _has_ffprobe(), reason="ffprobe not available")
def test_probe_filename_with_spaces_and_leading_dash(tmp_path: Path) -> None:
    """Filename with spaces and leading dash should work (RULE-06)."""
    # Leading dash
    dash_path = tmp_path / "-dash.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=1:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(dash_path),
        ],
        capture_output=True,
        check=True,
    )
    result = runner.invoke(app, ["probe", str(dash_path)])
    assert result.exit_code == ExitCode.SUCCESS.value, f"stderr: {result.stderr}"

    # Spaces
    space_path = tmp_path / "file with spaces.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=1:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(space_path),
        ],
        capture_output=True,
        check=True,
    )
    result = runner.invoke(app, ["probe", str(space_path)])
    assert result.exit_code == ExitCode.SUCCESS.value, f"stderr: {result.stderr}"


@pytest.mark.skipif(not _has_ffprobe(), reason="ffprobe not available")
def test_probe_rotated_video_shows_rotation_and_swap(tmp_path: Path) -> None:
    """Rotated phone video must report rotation and swapped display dimensions (FR-PRO-04)."""
    video_path = tmp_path / "rotated.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-noautorotate",
            "-display_rotation:v:0",
            "90",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=2:size=1920x1080:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )

    result = runner.invoke(app, ["probe", str(video_path)])
    assert result.exit_code == ExitCode.SUCCESS.value, f"stderr: {result.stderr}"
    output = result.stdout
    assert "rotation 90°" in output
    assert "baked into pixels" in output
    assert "1920x1080" in output


@pytest.mark.skipif(not _has_ffprobe(), reason="ffprobe not available")
def test_probe_nonexistent_file() -> None:
    result = runner.invoke(app, ["probe", "/nonexistent/path/video.mp4"])
    assert result.exit_code == ExitCode.USAGE.value
    assert "not found" in result.stderr.lower()


@pytest.mark.skipif(not _has_ffprobe(), reason="ffprobe not available")
def test_probe_directory_rejected(tmp_path: Path) -> None:
    result = runner.invoke(app, ["probe", str(tmp_path)])
    assert result.exit_code == ExitCode.USAGE.value
    assert "not a file" in result.stderr.lower()


@pytest.mark.skipif(not _has_ffprobe(), reason="ffprobe not available")
def test_probe_json_output(tmp_path: Path) -> None:
    """--json should output valid JSON with the ProbeData structure."""
    video_path = tmp_path / "test.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=1:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )

    result = runner.invoke(app, ["probe", str(video_path), "--json"])
    assert result.exit_code == ExitCode.SUCCESS.value, f"stderr: {result.stderr}"

    import json

    data = json.loads(result.stdout)
    assert "input_path" in data
    assert "format" in data
    assert "video_streams" in data
    assert "audio_streams" in data
    assert isinstance(data["video_streams"], list)
    assert len(data["video_streams"]) == 1
    v = data["video_streams"][0]
    assert v["codec_name"] in ("h264", "libx264")
    assert v["width"] == 320
    assert v["height"] == 240


@pytest.mark.skipif(not _has_ffprobe(), reason="ffprobe not available")
def test_probe_truncated_file_fails_integrity(tmp_path: Path) -> None:
    """A truncated file should be caught and rejected cleanly (FR-INP-03)."""
    # Create valid video first
    video_path = tmp_path / "valid.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=duration=1:size=320x240:rate=30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-an",
            str(video_path),
        ],
        capture_output=True,
        check=True,
    )
    # Truncate to 100 bytes
    truncated_path = tmp_path / "truncated.mp4"
    with open(video_path, "rb") as f_in, open(truncated_path, "wb") as f_out:
        f_out.write(f_in.read(100))

    result = runner.invoke(app, ["probe", str(truncated_path)])
    assert result.exit_code == ExitCode.USAGE.value
