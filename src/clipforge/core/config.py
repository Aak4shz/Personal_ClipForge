"""Configuration model, YAML loading, and precedence (FR-CFG-01 to FR-CFG-03).

Precedence is CLI over file over defaults: the pydantic model holds the
defaults, an optional YAML file names the keys it changes, and the overrides
mapping (CLI flags, using dotted key paths) is applied last. Validation
errors name the offending key (FR-CFG-02).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from clipforge.core.constants import (
    MAX_CLIP_SIZE_BYTES,
    MAX_FAULT_RETRIES,
    MAX_SIZE_ATTEMPTS,
    MAX_TOTAL_ENCODES,
    RETRY_DELAYS_SECONDS,
    SAFETY_MARGIN_PERCENT,
)
from clipforge.core.errors import UsageError
from clipforge.utils.paths import config_home, data_home, state_home

TailPolicy = Literal["keep", "merge_into_previous", "drop"]
SeekMode = Literal["fast", "accurate"]
FpsMode = Literal["preserve", "cfr"]
ProfileName = Literal["fast", "balanced", "best"]
OversizePolicy = Literal["fail", "fps", "downscale", "both"]
AudioChannelPolicy = Literal["keep", "stereo"]
HdrPolicy = Literal["keep", "tonemap"]
QualityMetric = Literal["none", "ssim", "psnr", "vmaf"]
HwAccelMode = Literal["off", "auto", "vaapi"]


def default_config_path() -> Path:
    """Return the user config path (FR-CFG-01: ``~/.config/clipforge/config.yaml``).

    $XDG_CONFIG_HOME moves the base directory when it names an absolute path.
    """
    return config_home() / "clipforge" / "config.yaml"


_SIZE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*(B|KiB|MiB|GiB)?$", re.IGNORECASE)
_SIZE_FACTOR = {"b": 1.0, "kib": float(1024), "mib": float(1024**2), "gib": float(1024**3)}


def _parse_byte_size(value: Any) -> Any:
    """Turn ``'4MiB'``-style strings into byte counts.

    Anything that is not a string (int, float, garbage) is passed through so
    pydantic's own error names the key (FR-CFG-02).
    """
    if not isinstance(value, str):
        return value
    match = _SIZE_PATTERN.match(value.strip())
    if match is None:
        raise ValueError("expected an integer byte count or a string like '4MiB'")
    number = float(match.group(1))
    unit = (match.group(2) or "B").lower()
    return math.ceil(number * _SIZE_FACTOR[unit])


class _Strict(BaseModel):
    """Base for all config sections: unknown keys are errors that name the key.

    Defaults are validated too, so a bad built-in value fails loudly instead
    of quietly producing a broken job.
    """

    model_config = ConfigDict(extra="forbid", validate_default=True)


class ProcessingConfig(_Strict):
    """Clip timing and seeking (blueprint section 18: processing)."""

    clip_duration_seconds: float = Field(default=10.0, gt=0.0)
    tail_policy: TailPolicy = "merge_into_previous"
    min_tail_seconds: float = Field(default=1.0, ge=0.0)
    seek_mode: SeekMode = "fast"
    fps_mode: FpsMode = "preserve"


class OutputConfig(_Strict):
    """Container, codecs, and the size law (blueprint section 18: output)."""

    container: Literal["webm"] = "webm"
    video_codec: Literal["libvpx-vp9"] = "libvpx-vp9"
    audio_codec: Literal["libopus"] = "libopus"
    max_size: int = Field(default=MAX_CLIP_SIZE_BYTES, ge=1)
    safety_margin_percent: int = Field(default=SAFETY_MARGIN_PERCENT, ge=0)
    profile: ProfileName = "balanced"
    on_oversize: OversizePolicy = "fail"
    audio_channels: AudioChannelPolicy = "keep"
    hdr: HdrPolicy = "keep"

    @field_validator("max_size", mode="before")
    @classmethod
    def _size_to_bytes(cls, value: Any) -> Any:
        return _parse_byte_size(value)


class OptimizerConfig(_Strict):
    """Size loop limits and two-pass fallback (blueprint section 18: optimizer)."""

    size_attempts: int = Field(default=MAX_SIZE_ATTEMPTS, ge=1)
    max_total_encodes: int = Field(default=MAX_TOTAL_ENCODES, ge=1)
    crf_start: int | Literal["auto"] = "auto"
    crf_max: int = Field(default=45, ge=0, le=63)
    two_pass_fallback: bool = True


class QualityConfig(_Strict):
    """Quality gate metric and thresholds (blueprint section 18: quality)."""

    metric: QualityMetric = "ssim"
    sample_every: int = Field(default=1, ge=1)
    ssim_min: float = Field(default=0.95, gt=0.0, le=1.0)
    vmaf_min: float = Field(default=80.0, ge=0.0, le=100.0)


class FaultToleranceConfig(_Strict):
    """Retries, delays, and the timeout factor (blueprint section 18: fault_tolerance)."""

    fault_retries: int = Field(default=MAX_FAULT_RETRIES, ge=0)
    retry_delays_seconds: list[float] = Field(default_factory=lambda: list(RETRY_DELAYS_SECONDS))
    timeout_factor: float = Field(default=20.0, gt=1.0)
    tolerate_corruption: bool = False


class PerformanceConfig(_Strict):
    """Resource limits (blueprint section 18: performance)."""

    concurrent_jobs: int = Field(default=1, ge=1)
    ffmpeg_threads: int = Field(default=3, ge=1)
    hw_accel: HwAccelMode = "off"
    max_ram_mb: int = Field(default=1500, ge=1)
    thermal_pause_celsius: int = Field(default=90, ge=0)


class PathsConfig(_Strict):
    """XDG locations (blueprint section 18: paths, NFR-09).

    Defaults resolve through the XDG base directories, so
    $XDG_DATA_HOME and $XDG_STATE_HOME move them on systems that set them.
    """

    database: Path = Field(default_factory=lambda: data_home() / "clipforge" / "clipforge.db")
    logs: Path = Field(default_factory=lambda: state_home() / "clipforge" / "logs")

    @field_validator("database", "logs", mode="after")
    @classmethod
    def _expand_home(cls, value: Path) -> Path:
        return value.expanduser()


class DashboardConfig(_Strict):
    """Dashboard toggle (blueprint section 18: dashboard)."""

    enabled: bool = True


class ClipForgeConfig(_Strict):
    """The full effective configuration."""

    version: Literal[2] = 2
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    optimizer: OptimizerConfig = Field(default_factory=OptimizerConfig)
    quality: QualityConfig = Field(default_factory=QualityConfig)
    fault_tolerance: FaultToleranceConfig = Field(default_factory=FaultToleranceConfig)
    performance: PerformanceConfig = Field(default_factory=PerformanceConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    dashboard: DashboardConfig = Field(default_factory=DashboardConfig)


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML config file, classifying every failure as UsageError."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise UsageError(
            what=f"cannot read config file: {path}",
            meaning=str(exc),
            fix="check that the path exists and is readable",
        ) from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise UsageError(
            what=f"cannot parse config file: {path}",
            meaning=str(exc).splitlines()[0],
            fix="correct the YAML syntax in the file",
        ) from exc
    if data is None:
        # An empty or comment-only file changes nothing; defaults stand
        return {}
    if not isinstance(data, dict):
        raise UsageError(
            what=f"config file is not a mapping: {path}",
            meaning="the top level must be keys and values, not a list or a scalar",
            fix="start the file with keys such as 'processing:' and 'output:'",
        )
    return data


def _merge_over(base: dict[str, Any], extra: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of base with extra applied over it, merging nested dicts."""
    merged = dict(base)
    for key, value in extra.items():
        current = merged.get(key)
        if isinstance(value, Mapping) and isinstance(current, dict):
            merged[key] = _merge_over(current, value)
        else:
            merged[key] = value
    return merged


def _expand_dotted(overrides: Mapping[str, Any]) -> dict[str, Any]:
    """Turn ``{'output.profile': 'best'}`` into ``{'output': {'profile': 'best'}}``."""
    expanded: dict[str, Any] = {}
    for key, value in overrides.items():
        head, separator, rest = key.partition(".")
        if not separator:
            expanded[key] = value
            continue
        branch = _expand_dotted({rest: value})
        existing = expanded.get(head)
        expanded[head] = _merge_over(existing, branch) if isinstance(existing, dict) else branch
    return expanded


def load_config(
    config_file: Path | None = None,
    overrides: Mapping[str, Any] | None = None,
) -> ClipForgeConfig:
    """Build the effective configuration: defaults, then file, then overrides.

    Args:
        config_file: Explicit file path. When omitted, only the built-in
            defaults are used; the CLI layer decides whether to read the
            default path (``default_config_path()``) if it exists.
        overrides: Dotted key paths mapped to values, applied last. This is
            how CLI flags outrank the file (FR-CFG-01).

    Returns:
        The validated configuration.

    Raises:
        UsageError: The file is missing, unreadable, not valid YAML, or the
            merged data fails validation. The message names the key.
    """
    data: dict[str, Any] = {}
    if config_file is not None:
        if not config_file.is_file():
            raise UsageError(
                what=f"config file not found: {config_file}",
                meaning="an explicitly named config file must exist",
                fix="pass an existing file path, or omit it to use only the defaults",
            )
        data = _read_yaml(config_file)

    if overrides:
        data = _merge_over(data, _expand_dotted(dict(overrides)))

    try:
        return ClipForgeConfig.model_validate(data)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise UsageError(
            what="invalid configuration",
            meaning=details,
            fix="correct the named keys in the config file or on the command line",
        ) from exc
