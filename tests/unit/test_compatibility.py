"""Unit tests for compatibility report generation (FR-PRO-03/04/05/06)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clipforge.probe.compatibility import build_report
from clipforge.probe.ffprobe import FFprobeResult
from clipforge.probe.metadata import normalize


def _build_probe_with(
    video_extra: dict[str, Any] | None = None,
    audio_extra: dict[str, Any] | None = None,
    format_name: str = "mov,mp4",
) -> Any:
    video_dict: dict[str, Any] = {
        "index": 0,
        "codec_name": "h264",
        "codec_type": "video",
        "width": 1920,
        "height": 1080,
        "pix_fmt": "yuv420p",
        "r_frame_rate": "30/1",
        "avg_frame_rate": "30/1",
        "time_base": "1/30",
        "duration": "10.0",
    }
    if video_extra:
        video_dict.update(video_extra)

    streams = [video_dict]
    if audio_extra is not None:
        audio_dict: dict[str, Any] = {
            "index": 1,
            "codec_name": "aac",
            "codec_type": "audio",
            "sample_rate": "48000",
            "channels": 2,
            "channel_layout": "stereo",
            "duration": "10.0",
        }
        audio_dict.update(audio_extra)
        streams.append(audio_dict)

    result = FFprobeResult(
        format={"format_name": format_name, "duration": "10.0", "nb_streams": len(streams)},
        streams=streams,
    )
    return normalize(result, Path("test.mp4"))


def test_standard_h264_aac_compatibility() -> None:
    probe = _build_probe_with(audio_extra={})
    report = build_report(probe)

    assert report.container.verdict == "converted"
    assert "webm" in report.container.output_format

    v_verdict = report.video_verdicts[0]
    assert v_verdict.verdict == "converted"
    assert v_verdict.output_codec == "libvpx-vp9"
    assert "decode h264 -> encode libvpx-vp9" in v_verdict.reason

    a_verdict = report.audio_verdicts[0]
    assert a_verdict.verdict == "converted"
    assert a_verdict.output_codec == "libopus"


def test_rotated_video_compatibility_reports_bake_in() -> None:
    probe = _build_probe_with(
        video_extra={
            "width": 1920,
            "height": 1080,
            "side_data_list": [{"side_data_type": "Display Matrix", "rotation": 90}],
        }
    )
    report = build_report(probe)
    v_verdict = report.video_verdicts[0]

    assert "rotation 90° baked into pixels: 1920x1080 -> 1080x1920 upright" in v_verdict.reason


def test_vp9_with_rotation_is_applied() -> None:
    probe = _build_probe_with(
        video_extra={
            "codec_name": "vp9",
            "width": 1920,
            "height": 1080,
            "tags": {"rotate": "270"},
        }
    )
    report = build_report(probe)
    v_verdict = report.video_verdicts[0]

    assert v_verdict.verdict == "applied"
    assert "rotation 270° baked into pixels" in v_verdict.reason


def test_hdr10_compatibility_reports_profile2_and_warning() -> None:
    probe = _build_probe_with(
        video_extra={
            "pix_fmt": "yuv420p10le",
            "bits_per_raw_sample": "10",
            "color_space": "bt2020nc",
            "color_primaries": "bt2020",
            "color_transfer": "smpte2084",
        }
    )
    report = build_report(probe)
    v_verdict = report.video_verdicts[0]

    assert "10-bit -> yuv420p10le" in v_verdict.reason
    assert "VP9 Profile 2" in v_verdict.reason
    assert "HDR keep" in v_verdict.reason


def test_422_chroma_downsampling_reported() -> None:
    probe = _build_probe_with(
        video_extra={
            "pix_fmt": "yuv422p",
        }
    )
    report = build_report(probe)
    v_verdict = report.video_verdicts[0]

    assert "downsample chroma to 4:2:0" in v_verdict.reason


def test_5_1_audio_and_resampling_reported() -> None:
    probe = _build_probe_with(
        audio_extra={
            "codec_name": "ac3",
            "sample_rate": "44100",
            "channels": 6,
            "channel_layout": "5.1(side)",
        }
    )
    report = build_report(probe)
    a_verdict = report.audio_verdicts[0]

    assert "6ch (5.1(side)) audio" in a_verdict.reason
    assert "resample 44100 Hz -> 48000 Hz" in a_verdict.reason
