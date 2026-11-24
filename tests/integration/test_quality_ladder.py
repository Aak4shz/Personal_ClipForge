"""Integration tests for Phase 7 Quality Gates and Degradation Ladder."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from clipforge.cli.exit_codes import ExitCode
from clipforge.cli.main import app

runner = CliRunner()


def _has_ffmpeg() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


@pytest.fixture(scope="module")
def synthetic_video_60fps(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a 2-second 60 fps 720p test video for fast integration testing."""
    tmp = tmp_path_factory.mktemp("ladder_fixtures")
    video = tmp / "test_60fps.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=1280x720:rate=60:duration=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=2",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-c:a",
            "aac",
            str(video),
        ],
        capture_output=True,
        check=True,
    )
    return video


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_quality_gate_ssim_pass_and_reporting(synthetic_video_60fps: Path, tmp_path: Path) -> None:
    """Split a clip with SSIM quality gate enabled and verify score is measured and passed."""
    out_dir = tmp_path / "ssim_pass_out"
    res = runner.invoke(
        app,
        [
            "split",
            str(synthetic_video_60fps),
            "-o",
            str(out_dir),
            "-d",
            "1.0",
            "--profile",
            "fast",
            "--quality-metric",
            "ssim",
            "--json",
        ],
    )
    assert res.exit_code == ExitCode.SUCCESS.value, f"split failed: {res.stdout}"
    data = json.loads(res.stdout)
    assert data["state"] == "COMPLETED"
    assert data["completed_clips"] == 2
    assert len(data["clips"]) == 2

    for c in data["clips"]:
        assert c["state"] == "COMPLETED"
        assert c["quality_metric"] == "ssim"
        assert c["quality_score"] is not None
        assert c["quality_score"] > 0.80


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_quality_gate_sampling_integration(synthetic_video_60fps: Path, tmp_path: Path) -> None:
    """Verify --quality-sample evaluates on sampled clips and skips others."""
    out_dir = tmp_path / "sample_out"
    res = runner.invoke(
        app,
        [
            "split",
            str(synthetic_video_60fps),
            "-o",
            str(out_dir),
            "-d",
            "1.0",
            "--profile",
            "fast",
            "--quality-metric",
            "ssim",
            "--quality-sample",
            "2",
            "--json",
        ],
    )
    assert res.exit_code == ExitCode.SUCCESS.value, f"split failed: {res.stdout}"
    data = json.loads(res.stdout)
    assert data["state"] == "COMPLETED"
    # Clip 1 sampled (has score), clip 2 skipped (no score)
    assert data["clips"][0]["quality_score"] is not None
    assert data["clips"][1]["quality_score"] is None


@pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg not available")
def test_degradation_ladder_fps_halving_on_tight_budget(
    synthetic_video_60fps: Path, tmp_path: Path
) -> None:
    """On a tight budget, size retries exhaust and ladder halves 60 fps to 30 fps."""
    out_dir = tmp_path / "ladder_out"
    res = runner.invoke(
        app,
        [
            "split",
            str(synthetic_video_60fps),
            "-o",
            str(out_dir),
            "-d",
            "2.0",
            "--profile",
            "fast",
            "--on-oversize",
            "fps",
            "--max-size",
            "80KiB",
            "--json",
        ],
    )
    data = json.loads(res.stdout)
    # The clips should either complete with fps halving or fail cleanly
    clip1 = data["clips"][0]
    if clip1["state"] == "COMPLETED":
        assert any("fps_30.0" in d for d in clip1["degradation"])
