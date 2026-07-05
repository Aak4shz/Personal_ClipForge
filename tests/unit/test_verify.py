"""Unit tests for post-encode clip verification (RULE-02, FR-OPT-01)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from clipforge.encoding.verify import verify_clip
from clipforge.probe.ffprobe import FFprobeError, FFprobeResult


def test_verify_nonexistent_file(tmp_path: Path) -> None:
    clip = tmp_path / "missing.webm"
    result = verify_clip(clip)
    assert not result.valid
    assert "file does not exist" in result.errors[0]


def test_verify_zero_byte_file(tmp_path: Path) -> None:
    clip = tmp_path / "empty.webm"
    clip.touch()
    result = verify_clip(clip)
    assert not result.valid
    assert "zero bytes" in result.errors[0]


def test_verify_oversize_file(tmp_path: Path) -> None:
    clip = tmp_path / "oversize.webm"
    # Create file larger than 4 MiB (4,194,304 bytes)
    with clip.open("wb") as f:
        f.seek(4_194_305 - 1)
        f.write(b"\0")

    # Mock ffprobe returning valid webm/vp9/opus
    mock_probe = FFprobeResult(
        format={"format_name": "matroska,webm", "duration": "10.0"},
        streams=[
            {"codec_type": "video", "codec_name": "vp9"},
            {"codec_type": "audio", "codec_name": "opus"},
        ],
    )

    with patch("clipforge.encoding.verify.run_ffprobe", return_value=mock_probe):
        result = verify_clip(clip)
        assert not result.valid
        assert result.is_oversize is True
        assert any("exceeds hard cap" in err for err in result.errors)


def test_verify_valid_clip(tmp_path: Path) -> None:
    clip = tmp_path / "valid.webm"
    clip.write_bytes(b"dummy webm data" * 100)

    mock_probe = FFprobeResult(
        format={"format_name": "matroska,webm", "duration": "10.0"},
        streams=[
            {"codec_type": "video", "codec_name": "vp9"},
            {"codec_type": "audio", "codec_name": "opus"},
        ],
    )

    with patch("clipforge.encoding.verify.run_ffprobe", return_value=mock_probe):
        result = verify_clip(clip, expected_duration=10.0)
        assert result.valid is True
        assert result.is_oversize is False
        assert result.format_name == "matroska,webm"
        assert result.video_codec == "vp9"
        assert result.audio_codec == "opus"
        assert result.duration_seconds == 10.0
        assert len(result.errors) == 0


def test_verify_wrong_codecs_and_container(tmp_path: Path) -> None:
    clip = tmp_path / "bad.mp4"
    clip.write_bytes(b"dummy mp4 data" * 10)

    mock_probe = FFprobeResult(
        format={"format_name": "mov,mp4,m4a,3gp,3g2,mj2", "duration": "10.0"},
        streams=[
            {"codec_type": "video", "codec_name": "h264"},
            {"codec_type": "audio", "codec_name": "aac"},
        ],
    )

    with patch("clipforge.encoding.verify.run_ffprobe", return_value=mock_probe):
        result = verify_clip(clip)
        assert not result.valid
        assert any("not WebM" in e for e in result.errors)
        assert any("video codec is not vp9" in e for e in result.errors)
        assert any("audio codec is not opus" in e for e in result.errors)


def test_verify_ffprobe_error(tmp_path: Path) -> None:
    clip = tmp_path / "corrupt.webm"
    clip.write_bytes(b"corrupt header")

    with patch(
        "clipforge.encoding.verify.run_ffprobe",
        side_effect=FFprobeError(input_path=clip, meaning="Failed to parse header"),
    ):
        result = verify_clip(clip)
        assert not result.valid
        assert any("Failed to parse header" in e for e in result.errors)
