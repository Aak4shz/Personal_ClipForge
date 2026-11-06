"""Config precedence and validation tests (FR-CFG-01 to FR-CFG-03)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from clipforge.core.config import default_config_path, load_config
from clipforge.core.constants import MAX_CLIP_SIZE_BYTES, TARGET_CLIP_SIZE_BYTES
from clipforge.core.errors import UsageError


def test_defaults_match_constants() -> None:
    config = load_config()
    assert config.version == 2
    assert config.processing.clip_duration_seconds == 10.0
    assert config.processing.tail_policy == "merge_into_previous"
    assert config.output.max_size == MAX_CLIP_SIZE_BYTES
    assert config.output.safety_margin_percent == 5
    assert config.output.profile == "balanced"
    assert config.output.on_oversize == "fail"
    assert config.optimizer.size_attempts == 4
    assert config.optimizer.max_total_encodes == 8
    assert config.fault_tolerance.fault_retries == 3
    assert config.fault_tolerance.retry_delays_seconds == [2.0, 5.0, 10.0]
    assert config.performance.ffmpeg_threads == 3
    assert config.performance.hw_accel == "off"
    assert config.quality.metric == "ssim"


def test_file_overrides_defaults(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("output:\n  profile: best\n", encoding="utf-8")
    config = load_config(config_file=config_file)
    assert config.output.profile == "best"
    # Keys the file does not name keep their defaults
    assert config.output.max_size == MAX_CLIP_SIZE_BYTES


def test_cli_overrides_beat_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("output:\n  profile: best\n", encoding="utf-8")
    config = load_config(config_file=config_file, overrides={"output.profile": "fast"})
    assert config.output.profile == "fast"


def test_dotted_override_reaches_nested_key() -> None:
    config = load_config(overrides={"fault_tolerance.timeout_factor": 15.0})
    assert config.fault_tolerance.timeout_factor == 15.0


def test_unknown_key_is_named_in_the_error(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("output:\n  profile: best\n  made_up: 1\n", encoding="utf-8")
    with pytest.raises(UsageError) as raised:
        load_config(config_file=config_file)
    assert "output.made_up" in str(raised.value)


def test_wrong_value_is_named_in_the_error() -> None:
    with pytest.raises(UsageError) as raised:
        load_config(overrides={"output.profile": "ultra"})
    assert "output.profile" in str(raised.value)


def test_missing_explicit_file_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(UsageError):
        load_config(config_file=tmp_path / "nope.yaml")


def test_empty_or_comment_only_yaml_keeps_defaults(tmp_path: Path) -> None:
    # Users create empty config files ahead of configuring; they must not be errors
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    commented = tmp_path / "commented.yaml"
    commented.write_text("# nothing here yet\n", encoding="utf-8")
    for config_file in (empty, commented):
        config = load_config(config_file=config_file)
        assert config.output.profile == "balanced"


def test_invalid_yaml_names_the_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.yaml"
    config_file.write_text("output: [broken\n", encoding="utf-8")
    with pytest.raises(UsageError) as raised:
        load_config(config_file=config_file)
    assert str(config_file) in str(raised.value)


def test_max_size_accepts_a_mib_string() -> None:
    config = load_config(overrides={"output.max_size": "4MiB"})
    assert config.output.max_size == MAX_CLIP_SIZE_BYTES


def test_target_is_the_ceiling_minus_the_margin() -> None:
    config = load_config()
    expected = math.ceil(MAX_CLIP_SIZE_BYTES * (100 - config.output.safety_margin_percent) / 100)
    assert TARGET_CLIP_SIZE_BYTES == expected == 3_984_589


def test_paths_expand_the_home_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME"):
        monkeypatch.delenv(var, raising=False)
    config = load_config()
    assert config.paths.database == Path.home() / ".local/share/clipforge/clipforge.db"
    assert config.paths.logs == Path.home() / ".local/state/clipforge/logs"


def test_xdg_environment_moves_the_locations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    assert default_config_path() == tmp_path / "config" / "clipforge" / "config.yaml"
    config = load_config()
    assert config.paths.database == tmp_path / "data" / "clipforge" / "clipforge.db"
    assert config.paths.logs == tmp_path / "state" / "clipforge" / "logs"


def test_relative_xdg_values_are_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", "relative/path")
    assert default_config_path() == Path.home() / ".config" / "clipforge" / "config.yaml"
