"""Quality gates and metric measurement (Phase 7, FR-OPT-08..10, FR-SPL-08).

Three tiers of quality enforcement:
- Tier 0: Container, codec, size, and timing/frame tolerance (always on).
- Tier 1: SSIM or PSNR filter pass with configurable thresholds and sampling.
- Tier 2: VMAF score when libvmaf is present; gracefully demotes to Tier 1 when absent.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from clipforge.core.config import QualityConfig
from clipforge.encoding.verify import ClipVerification, verify_clip
from clipforge.utils.timeutil import format_microseconds

# Tier 0 aliases (FR-OPT-08)
Tier0Result = ClipVerification
check_tier0_gate = verify_clip


class Runner(Protocol):
    """Subprocess runner protocol for test mocking (RULE-05)."""

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]: ...


def default_runner(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run FFmpeg subprocess with argument list and no shell (RULE-05)."""
    return subprocess.run(argv, capture_output=True, text=True, check=False, shell=False)


def _defend_path(path: Path) -> str:
    """Ensure path begins with / or ./ to prevent flag injection (RULE-06)."""
    p_str = str(path)
    if not p_str.startswith(("/", "./")):
        return f"./{p_str}"
    return p_str


@dataclass(frozen=True)
class QualityVerdict:
    """Outcome of quality evaluation for one clip."""

    passed: bool
    metric: str
    score: float | None
    threshold: float | None
    sampled: bool
    timing_mismatch: bool = False
    error: str | None = None


def is_libvmaf_available(runner: Runner = default_runner) -> bool:
    """Return True if installed FFmpeg has the libvmaf filter available."""
    try:
        completed = runner(["ffmpeg", "-hide_banner", "-filters"])
    except OSError:
        return False
    if completed.returncode != 0:
        return False
    return re.search(r"\b(libvmaf|vmaf)\b", completed.stdout) is not None


_SSIM_ALL_RE = re.compile(r"SSIM\s+.*All:\s*([0-9.]+)", re.IGNORECASE)
_PSNR_AVG_RE = re.compile(r"PSNR\s+.*average:\s*([0-9.]+)", re.IGNORECASE)
_VMAF_SCORE_RE = re.compile(r"VMAF\s+score:\s*([0-9.]+)", re.IGNORECASE)


def parse_quality_output(metric: str, stderr: str) -> float | None:
    """Parse quality score from FFmpeg filter stderr output.

    Args:
        metric: One of 'ssim', 'psnr', 'vmaf'.
        stderr: Captured stderr output of the filter pass.

    Returns:
        Float score if pattern matched, else None.
    """
    if metric == "ssim":
        match = _SSIM_ALL_RE.search(stderr)
        return float(match.group(1)) if match else None
    if metric == "psnr":
        match = _PSNR_AVG_RE.search(stderr)
        return float(match.group(1)) if match else None
    if metric == "vmaf":
        match = _VMAF_SCORE_RE.search(stderr)
        return float(match.group(1)) if match else None
    return None


def measure_quality(
    clip_path: Path,
    source_path: Path,
    start_us: int,
    duration_us: int,
    metric: str = "ssim",
    target_width: int | None = None,
    target_height: int | None = None,
    runner: Runner = default_runner,
) -> float:
    """Measure quality metric between reference source segment and encoded clip.

    Args:
        clip_path: Path to encoded clip file.
        source_path: Path to original source media.
        start_us: Clip seek offset in integer microseconds.
        duration_us: Clip duration in integer microseconds.
        metric: 'ssim', 'psnr', or 'vmaf'.
        target_width: Display width of encoded clip if downscaled.
        target_height: Display height of encoded clip if downscaled.
        runner: Subprocess runner for executing FFmpeg.

    Returns:
        Measured metric score as float.

    Raises:
        RuntimeError: If measurement pass fails or score cannot be parsed.
    """
    start_str = format_microseconds(start_us)
    duration_sec = duration_us / 1_000_000
    duration_str = f"{duration_sec:.6f}"

    filter_name = "libvmaf" if metric == "vmaf" else metric
    if target_width is not None and target_height is not None:
        filter_spec = f"[0:v]scale={target_width}:{target_height}[ref];[ref][1:v]{filter_name}"
    else:
        filter_spec = f"[0:v][1:v]{filter_name}"

    cmd = [
        "ffmpeg",
        "-nostdin",
        "-ss",
        start_str,
        "-t",
        duration_str,
        "-i",
        _defend_path(source_path),
        "-i",
        _defend_path(clip_path),
        "-filter_complex",
        filter_spec,
        "-f",
        "null",
        "-",
    ]

    completed = runner(cmd)
    if completed.returncode != 0:
        tail = completed.stderr.splitlines()[-5:] if completed.stderr else []
        err_detail = "; ".join(line.strip() for line in tail)
        raise RuntimeError(
            f"quality filter pass failed (exit {completed.returncode}): {err_detail}"
        )

    score = parse_quality_output(metric, completed.stderr)
    if score is None:
        raise RuntimeError(f"failed to parse {metric} score from FFmpeg output")

    return score


def check_quality_gate(
    clip_path: Path,
    source_path: Path,
    start_us: int,
    duration_us: int,
    config: QualityConfig,
    clip_index: int = 1,
    target_width: int | None = None,
    target_height: int | None = None,
    runner: Runner = default_runner,
) -> QualityVerdict:
    """Evaluate quality gate for a clip adhering to metric, threshold, and sampling rules.

    Args:
        clip_path: Path to encoded clip file.
        source_path: Path to original source media.
        start_us: Clip start offset in microseconds.
        duration_us: Clip duration in microseconds.
        config: Configured quality settings.
        clip_index: 1-based index of clip.
        target_width: Downscaled clip width if degraded.
        target_height: Downscaled clip height if degraded.
        runner: Subprocess runner for executing FFmpeg.

    Returns:
        QualityVerdict with evaluation details.
    """
    if config.metric == "none":
        return QualityVerdict(
            passed=True,
            metric="none",
            score=None,
            threshold=None,
            sampled=False,
        )

    # Check sampling (FR-OPT-09: --quality-sample N)
    sample_every = max(1, config.sample_every)
    is_sampled = ((clip_index - 1) % sample_every) == 0
    if not is_sampled:
        return QualityVerdict(
            passed=True,
            metric=config.metric,
            score=None,
            threshold=None,
            sampled=False,
        )

    # Metric selection and fallback (Tier 2 VMAF demotes to SSIM if libvmaf absent)
    metric = config.metric
    if metric == "vmaf" and not is_libvmaf_available(runner):
        metric = "ssim"

    threshold: float
    if metric == "ssim":
        threshold = config.ssim_min
    elif metric == "psnr":
        threshold = config.psnr_min
    else:  # vmaf
        threshold = config.vmaf_min

    try:
        score = measure_quality(
            clip_path=clip_path,
            source_path=source_path,
            start_us=start_us,
            duration_us=duration_us,
            metric=metric,
            target_width=target_width,
            target_height=target_height,
            runner=runner,
        )
    except RuntimeError as exc:
        return QualityVerdict(
            passed=False,
            metric=metric,
            score=None,
            threshold=threshold,
            sampled=True,
            error=str(exc),
        )

    passed = score >= threshold
    return QualityVerdict(
        passed=passed,
        metric=metric,
        score=score,
        threshold=threshold,
        sampled=True,
    )
