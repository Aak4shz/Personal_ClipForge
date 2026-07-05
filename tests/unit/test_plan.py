"""Unit tests for the job planning orchestrator (plan_job, Phase 3)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from clipforge.core.constants import TARGET_CLIP_SIZE_BYTES
from clipforge.core.errors import UsageError
from clipforge.planner.plan import plan_job
from clipforge.probe.ffprobe import FFprobeResult
from clipforge.probe.metadata import ProbeData, normalize


def _make_dummy_probe(
    duration: float = 600.0,
    width: int = 1920,
    height: int = 1080,
    fps: float = 30.0,
    channels: int = 2,
) -> ProbeData:
    payload: dict[str, Any] = {
        "format": {
            "format_name": "mov,mp4,m4a,3gp,3g2,mj2",
            "format_long_name": "QuickTime / MOV",
            "start_time": "0.000000",
            "duration": str(duration),
            "size": "100000000",
            "bit_rate": "1333333",
            "nb_streams": 2 if channels > 0 else 1,
            "nb_programs": 0,
            "tags": {},
        },
        "streams": [
            {
                "index": 0,
                "codec_name": "h264",
                "codec_long_name": "H.264 / AVC",
                "profile": "High",
                "codec_type": "video",
                "width": width,
                "height": height,
                "coded_width": width,
                "coded_height": height,
                "display_aspect_ratio": "16:9",
                "sample_aspect_ratio": "1:1",
                "pix_fmt": "yuv420p",
                "bits_per_raw_sample": "8",
                "color_space": "bt709",
                "color_range": "tv",
                "color_primaries": "bt709",
                "color_transfer": "bt709",
                "r_frame_rate": f"{int(fps)}/1",
                "avg_frame_rate": f"{int(fps)}/1",
                "time_base": f"1/{int(fps)}",
                "duration": str(duration),
                "nb_frames": str(int(duration * fps)),
                "disposition": {},
                "tags": {},
            }
        ],
    }
    if channels > 0:
        payload["streams"].append(
            {
                "index": 1,
                "codec_name": "aac",
                "codec_long_name": "AAC",
                "profile": "LC",
                "codec_type": "audio",
                "sample_rate": "48000",
                "channels": channels,
                "channel_layout": "stereo" if channels == 2 else "mono",
                "bit_rate": "128000",
                "time_base": "1/48000",
                "duration": str(duration),
                "disposition": {},
                "tags": {},
            }
        )

    res = FFprobeResult(format=payload["format"], streams=payload["streams"])
    return normalize(res, Path("/fake/video.mp4"))


def test_plan_ten_minute_video() -> None:
    probe = _make_dummy_probe(duration=600.0)
    plan = plan_job(probe, clip_duration_seconds=10.0)

    assert plan.clip_count == 60
    assert plan.clip_duration_us == 10_000_000
    assert plan.total_duration_us == 600_000_000
    assert plan.source_start_us == 0
    assert plan.tail_decision == "none"
    assert plan.tail_us == 0
    assert plan.budget.target_bytes == TARGET_CLIP_SIZE_BYTES
    assert plan.budget.audio_bps == 64_000
    assert plan.budget.video_bps == 3_123_671
    assert plan.feasibility.verdict == "comfortable"
    assert plan.estimated_total_bytes == 60 * TARGET_CLIP_SIZE_BYTES


def test_plan_with_range_constraints() -> None:
    probe = _make_dummy_probe(duration=600.0)
    plan = plan_job(
        probe,
        clip_duration_seconds=10.0,
        start_time_spec="00:01:00",  # 60s
        end_time_spec="00:02:00",  # 120s
    )
    # 60s total duration = 6 clips of 10s
    assert plan.clip_count == 6
    assert plan.total_duration_us == 60_000_000
    assert plan.source_start_us == 60_000_000
    assert plan.boundaries[0].start_us == 60_000_000
    assert plan.boundaries[0].end_us == 70_000_000
    assert plan.boundaries[-1].start_us == 110_000_000
    assert plan.boundaries[-1].end_us == 120_000_000


def test_plan_invalid_range_raises() -> None:
    probe = _make_dummy_probe(duration=600.0)
    with pytest.raises(UsageError, match="invalid range"):
        plan_job(probe, start_time_spec="00:05:00", end_time_spec="00:01:00")


def test_plan_invalid_clip_duration_raises() -> None:
    probe = _make_dummy_probe(duration=600.0)
    with pytest.raises(UsageError, match="invalid clip duration"):
        plan_job(probe, clip_duration_seconds=0.5)
    with pytest.raises(UsageError, match="invalid clip duration"):
        plan_job(probe, clip_duration_seconds=650.0)
