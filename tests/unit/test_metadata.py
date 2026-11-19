"""Unit tests for metadata normalization (pure function, recorded ffprobe JSON)."""

from __future__ import annotations

from fractions import Fraction
from pathlib import Path
from typing import Any

from clipforge.probe.ffprobe import FFprobeResult
from clipforge.probe.metadata import ProbeData, normalize

# Minimal recorded ffprobe JSON for a 1080p30 H.264 + AAC MP4
SAMPLE_FFPROBE_JSON: dict[str, Any] = {
    "format": {
        "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
        "format_long_name": "QuickTime / MOV",
        "start_time": "0.000000",
        "duration": "10.000000",
        "size": "12345678",
        "bit_rate": "9876543",
        "nb_streams": 2,
        "nb_programs": 0,
        "tags": {
            "major_brand": "isom",
            "minor_version": "512",
            "compatible_brands": "isomiso2avc1mp41",
            "encoder": "Lavf58.29.100",
        },
    },
    "streams": [
        {
            "index": 0,
            "codec_name": "h264",
            "codec_long_name": "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10",
            "profile": "High",
            "codec_type": "video",
            "width": 1920,
            "height": 1080,
            "coded_width": 1920,
            "coded_height": 1088,
            "display_aspect_ratio": "16:9",
            "sample_aspect_ratio": "1:1",
            "pix_fmt": "yuv420p",
            "bits_per_raw_sample": "8",
            "color_space": "bt709",
            "color_range": "tv",
            "color_primaries": "bt709",
            "color_transfer": "bt709",
            "r_frame_rate": "30/1",
            "avg_frame_rate": "30/1",
            "time_base": "1/30",
            "start_pts": 0,
            "start_time": "0.000000",
            "duration_ts": 300,
            "duration": "10.000000",
            "nb_frames": "300",
            "disposition": {
                "default": 1,
                "dub": 0,
                "original": 0,
                "comment": 0,
                "attached_pic": 0,
            },
            "tags": {
                "language": "und",
                "handler_name": "VideoHandler",
            },
        },
        {
            "index": 1,
            "codec_name": "aac",
            "codec_long_name": "AAC (Advanced Audio Coding)",
            "profile": "LC",
            "codec_type": "audio",
            "sample_rate": "48000",
            "channels": 2,
            "channel_layout": "stereo",
            "bit_rate": "128000",
            "time_base": "1/48000",
            "start_time": "0.000000",
            "duration": "10.000000",
            "disposition": {
                "default": 1,
                "dub": 0,
                "original": 0,
                "comment": 0,
                "attached_pic": 0,
            },
            "tags": {
                "language": "und",
                "handler_name": "SoundHandler",
            },
        },
    ],
}


def _make_result() -> FFprobeResult:
    return FFprobeResult(
        format=SAMPLE_FFPROBE_JSON["format"],
        streams=SAMPLE_FFPROBE_JSON["streams"],
    )


def test_normalize_produces_probe_data() -> None:
    result = _make_result()
    probe = normalize(result, Path("test.mp4"))

    assert isinstance(probe, ProbeData)
    assert probe.input_path == Path("test.mp4")
    assert probe.has_video
    assert probe.has_audio
    assert len(probe.video_streams) == 1
    assert len(probe.audio_streams) == 1


def test_video_stream_fields_populated() -> None:
    result = _make_result()
    probe = normalize(result, Path("test.mp4"))
    v = probe.primary_video
    assert v is not None

    assert v.index == 0
    assert v.codec_name == "h264"
    assert v.codec_long_name == "H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10"
    assert v.profile == "High"
    assert v.width == 1920
    assert v.height == 1080
    assert v.coded_width == 1920
    assert v.coded_height == 1088
    assert v.display_aspect_ratio == "16:9"
    assert v.sample_aspect_ratio == "1:1"
    assert v.pix_fmt == "yuv420p"
    assert v.bits_per_raw_sample == 8
    assert v.color_space == "bt709"
    assert v.color_range == "tv"
    assert v.color_primaries == "bt709"
    assert v.color_transfer == "bt709"
    assert v.r_frame_rate == Fraction(30, 1)
    assert v.avg_frame_rate == Fraction(30, 1)
    assert v.time_base == Fraction(1, 30)
    assert v.start_pts == 0
    assert v.start_time == 0.0
    assert v.duration_ts == 300
    assert v.duration == 10.0
    assert v.nb_frames == 300
    assert v.is_vfr is False  # r_frame_rate == avg_frame_rate
    assert v.disposition == {
        "default": True,
        "dub": False,
        "original": False,
        "comment": False,
        "attached_pic": False,
    }
    assert v.tags == {"language": "und", "handler_name": "VideoHandler"}


def test_audio_stream_fields_populated() -> None:
    result = _make_result()
    probe = normalize(result, Path("test.mp4"))
    a = probe.primary_audio
    assert a is not None

    assert a.index == 1
    assert a.codec_name == "aac"
    assert a.codec_long_name == "AAC (Advanced Audio Coding)"
    assert a.profile == "LC"
    assert a.sample_rate == 48000
    assert a.channels == 2
    assert a.channel_layout == "stereo"
    assert a.bit_rate == 128000
    assert a.time_base == Fraction(1, 48000)
    assert a.start_time == 0.0
    assert a.duration == 10.0
    assert a.disposition == {
        "default": True,
        "dub": False,
        "original": False,
        "comment": False,
        "attached_pic": False,
    }
    assert a.tags == {"language": "und", "handler_name": "SoundHandler"}


def test_format_fields_populated() -> None:
    result = _make_result()
    probe = normalize(result, Path("test.mp4"))
    f = probe.format

    assert f.format_name == "mov,mp4,m4a,3gp,3g2,mj2"
    assert f.format_long_name == "QuickTime / MOV"
    assert f.start_time == 0.0
    assert f.duration == 10.0
    assert f.size == 12345678
    assert f.bit_rate == 9876543
    assert f.nb_streams == 2
    assert f.nb_programs == 0
    assert f.tags == {
        "major_brand": "isom",
        "minor_version": "512",
        "compatible_brands": "isomiso2avc1mp41",
        "encoder": "Lavf58.29.100",
    }


def test_vfr_detection_when_rates_differ() -> None:
    # Same JSON but with different r/avg frame rates
    data: dict[str, Any] = {
        "format": SAMPLE_FFPROBE_JSON["format"],
        "streams": [
            {
                **SAMPLE_FFPROBE_JSON["streams"][0],
                "r_frame_rate": "60/1",
                "avg_frame_rate": "30/1",
            },
            SAMPLE_FFPROBE_JSON["streams"][1],
        ],
    }
    result = FFprobeResult(format=data["format"], streams=data["streams"])
    probe = normalize(result, Path("test.mp4"))
    assert probe.primary_video is not None
    assert probe.primary_video.is_vfr is True


def test_missing_optional_fields_are_none() -> None:
    # Minimal stream with only required fields
    data: dict[str, Any] = {
        "format": {
            "format_name": "matroska,webm",
            "format_long_name": "Matroska / WebM",
            "duration": "5.0",
            "size": "1000",
            "bit_rate": "1000",
            "nb_streams": 1,
            "nb_programs": 0,
            "tags": {},
        },
        "streams": [
            {
                "index": 0,
                "codec_name": "vp9",
                "codec_long_name": "VP9",
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "24/1",
                "avg_frame_rate": "24/1",
                "time_base": "1/24",
            },
        ],
    }
    result = FFprobeResult(format=data["format"], streams=data["streams"])
    probe = normalize(result, Path("test.webm"))
    v = probe.primary_video
    assert v is not None
    assert v.profile is None
    assert v.display_aspect_ratio is None
    assert v.sample_aspect_ratio is None
    assert v.bits_per_raw_sample is None
    assert v.color_space is None
    assert v.color_range is None
    assert v.color_primaries is None
    assert v.color_transfer is None
    assert v.start_pts is None
    assert v.start_time is None
    assert v.duration_ts is None
    assert v.duration is None
    assert v.nb_frames is None
    assert v.disposition == {}
    assert v.tags == {}


def test_duration_fallback_chain() -> None:
    # Format has no duration, video has duration
    data: dict[str, Any] = {
        "format": {
            "format_name": "matroska,webm",
            "format_long_name": "Matroska / WebM",
            "duration": None,
            "size": "1000",
            "bit_rate": "1000",
            "nb_streams": 1,
            "nb_programs": 0,
            "tags": {},
        },
        "streams": [
            {
                "index": 0,
                "codec_name": "vp9",
                "codec_long_name": "VP9",
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "24/1",
                "avg_frame_rate": "24/1",
                "time_base": "1/24",
                "duration": "5.0",
            },
        ],
    }
    result = FFprobeResult(format=data["format"], streams=data["streams"])
    probe = normalize(result, Path("test.webm"))
    assert probe.duration_seconds == 5.0


def test_rotation_from_display_matrix_swaps_display_dimensions() -> None:
    data: dict[str, Any] = {
        "format": {"format_name": "mov,mp4", "duration": "1.0", "nb_streams": 1},
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1920,
                "height": 1080,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "side_data_list": [
                    {
                        "side_data_type": "Display Matrix",
                        "rotation": 90,
                    }
                ],
            }
        ],
    }
    result = FFprobeResult(format=data["format"], streams=data["streams"])
    probe = normalize(result, Path("rotated.mp4"))
    v = probe.primary_video
    assert v is not None
    assert v.rotation == 90
    assert v.width == 1920
    assert v.height == 1080
    assert v.display_width == 1080
    assert v.display_height == 1920
    assert v.display_resolution == "1080x1920"


def test_rotation_from_tags_and_negative_rotation() -> None:
    data: dict[str, Any] = {
        "format": {"format_name": "mov,mp4", "duration": "1.0", "nb_streams": 1},
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_type": "video",
                "width": 1280,
                "height": 720,
                "pix_fmt": "yuv420p",
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "tags": {"rotate": "-90"},
            }
        ],
    }
    result = FFprobeResult(format=data["format"], streams=data["streams"])
    probe = normalize(result, Path("rotated.mp4"))
    v = probe.primary_video
    assert v is not None
    assert v.rotation == 270  # -90 deg == 270 deg
    assert v.display_width == 720
    assert v.display_height == 1280
