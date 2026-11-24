"""Unit tests for quality gates and metric measurement (Phase 7, FR-OPT-08..10)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from clipforge.core.config import QualityConfig
from clipforge.optimizer.quality import (
    check_quality_gate,
    check_tier0_gate,
    is_libvmaf_available,
    measure_quality,
    parse_quality_output,
)
from clipforge.probe.ffprobe import FFprobeResult


def test_parse_quality_output_ssim() -> None:
    stderr = (
        "[Parsed_ssim_0 @ 0x55d7f8] SSIM Y:0.965213 (14.585721) "
        "U:0.978124 (16.600122) V:0.979011 (16.780123) All:0.968945 (15.078291)\n"
    )
    score = parse_quality_output("ssim", stderr)
    assert score == pytest.approx(0.968945)

    assert parse_quality_output("ssim", "No match here") is None


def test_parse_quality_output_psnr() -> None:
    stderr = (
        "[Parsed_psnr_0 @ 0x55abc] PSNR y:37.452 u:42.123 v:43.001 "
        "average:38.765 min:31.234 max:inf\n"
    )
    score = parse_quality_output("psnr", stderr)
    assert score == pytest.approx(38.765)

    assert parse_quality_output("psnr", "invalid output") is None


def test_parse_quality_output_vmaf() -> None:
    stderr = "[libvmaf @ 0x55123] VMAF score: 86.452109\n"
    score = parse_quality_output("vmaf", stderr)
    assert score == pytest.approx(86.452109)

    assert parse_quality_output("vmaf", "nothing") is None


def test_is_libvmaf_available() -> None:
    def runner_with_vmaf(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout=" ... libvmaf V->V ...\n", stderr="")

    def runner_without_vmaf(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 0, stdout=" ... ssim V->V ...\n", stderr="")

    def runner_fail(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="error")

    assert is_libvmaf_available(runner_with_vmaf) is True
    assert is_libvmaf_available(runner_without_vmaf) is False
    assert is_libvmaf_available(runner_fail) is False


def test_measure_quality_command_and_result(tmp_path: Path) -> None:
    clip_path = tmp_path / "clip.webm"
    clip_path.touch()
    source_path = tmp_path / "source.mp4"
    source_path.touch()

    executed_cmds: list[list[str]] = []

    def mock_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        executed_cmds.append(argv)
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout="",
            stderr="[Parsed_ssim_0 @ 0x1] SSIM Y:0.95 U:0.96 V:0.96 All:0.961000 (14.0)\n",
        )

    # Standard (non-downscaled) measurement
    score = measure_quality(
        clip_path=clip_path,
        source_path=source_path,
        start_us=10_000_000,
        duration_us=10_000_000,
        metric="ssim",
        runner=mock_runner,
    )
    assert score == pytest.approx(0.961)
    assert len(executed_cmds) == 1
    cmd = executed_cmds[0]
    assert "-filter_complex" in cmd
    assert cmd[cmd.index("-filter_complex") + 1] == "[0:v][1:v]ssim"

    # Downscaled measurement applies reference scaling filtergraph
    score_downscaled = measure_quality(
        clip_path=clip_path,
        source_path=source_path,
        start_us=10_000_000,
        duration_us=10_000_000,
        metric="ssim",
        target_width=1280,
        target_height=720,
        runner=mock_runner,
    )
    assert score_downscaled == pytest.approx(0.961)
    cmd2 = executed_cmds[1]
    assert cmd2[cmd2.index("-filter_complex") + 1] == "[0:v]scale=1280:720[ref];[ref][1:v]ssim"


def test_measure_quality_subprocess_failure(tmp_path: Path) -> None:
    clip_path = tmp_path / "clip.webm"
    clip_path.touch()
    source_path = tmp_path / "source.mp4"
    source_path.touch()

    def mock_failing_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="Filter error: invalid args")

    with pytest.raises(RuntimeError, match="quality filter pass failed"):
        measure_quality(
            clip_path=clip_path,
            source_path=source_path,
            start_us=0,
            duration_us=10_000_000,
            runner=mock_failing_runner,
        )


def test_check_quality_gate_metric_none(tmp_path: Path) -> None:
    cfg = QualityConfig(metric="none")
    verdict = check_quality_gate(
        clip_path=tmp_path / "clip.webm",
        source_path=tmp_path / "source.mp4",
        start_us=0,
        duration_us=10_000_000,
        config=cfg,
    )
    assert verdict.passed is True
    assert verdict.metric == "none"
    assert verdict.sampled is False


def test_check_quality_gate_sampling(tmp_path: Path) -> None:
    # sample_every = 3 -> evaluate on clip 1 and 4, skip clips 2 and 3
    cfg = QualityConfig(metric="ssim", sample_every=3)

    calls = 0

    def mock_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="SSIM All:0.96 (14.0)\n")

    # Clip 1: evaluated
    v1 = check_quality_gate(
        clip_path=tmp_path / "c.webm",
        source_path=tmp_path / "s.mp4",
        start_us=0,
        duration_us=10_000_000,
        config=cfg,
        clip_index=1,
        runner=mock_runner,
    )
    assert v1.sampled is True
    assert v1.passed is True
    assert calls == 1

    # Clip 2: skipped
    v2 = check_quality_gate(
        clip_path=tmp_path / "c.webm",
        source_path=tmp_path / "s.mp4",
        start_us=10_000_000,
        duration_us=10_000_000,
        config=cfg,
        clip_index=2,
        runner=mock_runner,
    )
    assert v2.sampled is False
    assert v2.passed is True
    assert calls == 1  # No new subprocess run

    # Clip 4: evaluated
    v4 = check_quality_gate(
        clip_path=tmp_path / "c.webm",
        source_path=tmp_path / "s.mp4",
        start_us=30_000_000,
        duration_us=10_000_000,
        config=cfg,
        clip_index=4,
        runner=mock_runner,
    )
    assert v4.sampled is True
    assert calls == 2


def test_check_quality_gate_vmaf_fallback_when_unavailable(tmp_path: Path) -> None:
    # When libvmaf is absent, fallback to SSIM (FR-OPT-08)
    cfg = QualityConfig(metric="vmaf", vmaf_min=80.0, ssim_min=0.95)

    def mock_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
        if "-filters" in argv:
            # filters list without libvmaf
            return subprocess.CompletedProcess(argv, 0, stdout="ssim V->V\n", stderr="")
        # Metric measurement pass: return SSIM output
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="SSIM All:0.965 (14.0)\n")

    verdict = check_quality_gate(
        clip_path=tmp_path / "c.webm",
        source_path=tmp_path / "s.mp4",
        start_us=0,
        duration_us=10_000_000,
        config=cfg,
        runner=mock_runner,
    )
    # Demoted to ssim and passed
    assert verdict.metric == "ssim"
    assert verdict.threshold == 0.95
    assert verdict.score == pytest.approx(0.965)
    assert verdict.passed is True


def test_check_quality_gate_threshold_pass_and_fail(tmp_path: Path) -> None:
    cfg = QualityConfig(metric="psnr", psnr_min=35.0)

    # Passing case (36.5 >= 35.0)
    v_pass = check_quality_gate(
        clip_path=tmp_path / "c.webm",
        source_path=tmp_path / "s.mp4",
        start_us=0,
        duration_us=10_000_000,
        config=cfg,
        runner=lambda a: subprocess.CompletedProcess(a, 0, stdout="", stderr="PSNR average:36.5\n"),
    )
    assert v_pass.passed is True
    assert v_pass.score == pytest.approx(36.5)

    # Failing case (33.0 < 35.0)
    v_fail = check_quality_gate(
        clip_path=tmp_path / "c.webm",
        source_path=tmp_path / "s.mp4",
        start_us=0,
        duration_us=10_000_000,
        config=cfg,
        runner=lambda a: subprocess.CompletedProcess(a, 0, stdout="", stderr="PSNR average:33.0\n"),
    )
    assert v_fail.passed is False
    assert v_fail.score == pytest.approx(33.0)


def test_check_tier0_gate_timing_and_resolution(tmp_path: Path) -> None:
    clip = tmp_path / "clip.webm"
    clip.write_bytes(b"dummy")

    # Mock ffprobe returning 1920x1080 @ 10.0s
    mock_probe = FFprobeResult(
        format={"format_name": "matroska,webm", "duration": "10.0"},
        streams=[
            {"codec_type": "video", "codec_name": "vp9", "width": 1920, "height": 1080},
            {"codec_type": "audio", "codec_name": "opus"},
        ],
    )

    with patch("clipforge.encoding.verify.run_ffprobe", return_value=mock_probe):
        # 1. Matching resolution and duration -> valid
        res_ok = check_tier0_gate(
            clip,
            expected_duration=10.0,
            expected_fps=30.0,
            expected_width=1920,
            expected_height=1080,
        )
        assert res_ok.valid is True
        assert res_ok.timing_mismatch is False

        # 2. Resolution mismatch (downscaled expected 1280x720) -> invalid
        res_res_bad = check_tier0_gate(
            clip,
            expected_duration=10.0,
            expected_width=1280,
            expected_height=720,
        )
        assert res_res_bad.valid is False
        assert any("width 1920 does not match expected 1280" in e for e in res_res_bad.errors)

        # 3. Timing mismatch (10.0s vs expected 8.0s > tolerance) -> timing_mismatch = True
        res_timing_bad = check_tier0_gate(
            clip,
            expected_duration=8.0,
            expected_fps=30.0,
        )
        assert res_timing_bad.valid is False
        assert res_timing_bad.timing_mismatch is True
