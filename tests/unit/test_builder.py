"""Unit tests for FFmpeg argument building (FR-ENC-01..07, RULE-05, RULE-06, RULE-29)."""

from __future__ import annotations

from pathlib import Path

from clipforge.encoding.builder import build_encode_command


def test_build_encode_command_default_balanced() -> None:
    input_path = Path("/media/videos/input.mp4")
    output_part = Path("/media/videos/.clipforge_tmp/clip_0000.webm.part")

    cmd = build_encode_command(
        input_path=input_path,
        output_part_path=output_part,
        start_us=0,
        duration_us=10_000_000,
        video_bps=3_123_671,
        audio_bps=64_000,
        width=1920,
        height=1080,
        fps=30.0,
        profile="balanced",
    )

    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    assert "-nostdin" in cmd

    # Seek before input
    ss_idx = cmd.index("-ss")
    i_idx = cmd.index("-i")
    assert ss_idx < i_idx
    assert cmd[ss_idx + 1] == "00:00:00.000000"
    assert cmd[i_idx + 1] == "/media/videos/input.mp4"

    # Duration
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "10.000000"

    # Balanced profile settings
    assert cmd[cmd.index("-c:v") + 1] == "libvpx-vp9"
    assert cmd[cmd.index("-deadline") + 1] == "good"
    assert cmd[cmd.index("-cpu-used") + 1] == "2"
    assert cmd[cmd.index("-row-mt") + 1] == "1"
    assert cmd[cmd.index("-threads") + 1] == "3"
    assert cmd[cmd.index("-tile-columns") + 1] == "2"
    assert cmd[cmd.index("-auto-alt-ref") + 1] == "1"
    assert cmd[cmd.index("-lag-in-frames") + 1] == "25"
    assert cmd[cmd.index("-g") + 1] == "300"
    assert cmd[cmd.index("-crf") + 1] == "32"
    assert cmd[cmd.index("-b:v") + 1] == "3123671"
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"

    # Audio
    assert cmd[cmd.index("-c:a") + 1] == "libopus"
    assert cmd[cmd.index("-b:a") + 1] == "64000"

    # Output
    assert cmd[cmd.index("-f") + 1] == "webm"
    assert cmd[-1] == "/media/videos/.clipforge_tmp/clip_0000.webm.part"


def test_build_encode_command_fast_profile() -> None:
    cmd = build_encode_command(
        input_path=Path("/input.mp4"),
        output_part_path=Path("/out.webm.part"),
        start_us=10_000_000,
        duration_us=10_000_000,
        video_bps=2_000_000,
        profile="fast",
    )
    assert cmd[cmd.index("-cpu-used") + 1] == "4"


def test_build_encode_command_four_k_settings() -> None:
    cmd = build_encode_command(
        input_path=Path("/input.mp4"),
        output_part_path=Path("/out.webm.part"),
        start_us=0,
        duration_us=10_000_000,
        video_bps=3_000_000,
        width=3840,
        height=2160,
        fps=60.0,
    )
    # 4K has 8 tile columns and reduced lag-in-frames to hold RAM
    assert cmd[cmd.index("-tile-columns") + 1] == "3"
    assert cmd[cmd.index("-lag-in-frames") + 1] == "16"
    assert cmd[cmd.index("-g") + 1] == "600"  # 10s * 60fps


def test_build_encode_command_ten_bit() -> None:
    cmd = build_encode_command(
        input_path=Path("/input.mp4"),
        output_part_path=Path("/out.webm.part"),
        start_us=0,
        duration_us=10_000_000,
        video_bps=3_000_000,
        pix_fmt="yuv420p10le",
        bits_per_raw_sample=10,
    )
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p10le"


def test_build_encode_command_no_audio() -> None:
    cmd = build_encode_command(
        input_path=Path("/input.mp4"),
        output_part_path=Path("/out.webm.part"),
        start_us=0,
        duration_us=10_000_000,
        video_bps=3_000_000,
        has_audio=False,
    )
    assert "-an" in cmd
    assert "-c:a" not in cmd


def test_build_encode_command_multichannel_downmix() -> None:
    cmd = build_encode_command(
        input_path=Path("/input.mp4"),
        output_part_path=Path("/out.webm.part"),
        start_us=0,
        duration_us=10_000_000,
        video_bps=3_000_000,
        has_audio=True,
        audio_channels=6,
        audio_channels_policy="stereo",
    )
    ac_idx = cmd.index("-ac")
    assert cmd[ac_idx + 1] == "2"


def test_build_encode_command_two_pass() -> None:
    # Pass 1
    cmd1 = build_encode_command(
        input_path=Path("/input.mp4"),
        output_part_path=Path("/out.webm.part"),
        start_us=0,
        duration_us=10_000_000,
        video_bps=3_000_000,
        pass_number=1,
        passlogfile=Path("/tmp/clip_0000"),
    )
    assert cmd1[cmd1.index("-pass") + 1] == "1"
    assert cmd1[cmd1.index("-passlogfile") + 1] == "/tmp/clip_0000"
    assert "-an" in cmd1
    assert cmd1[-2:] == ["-f", "null"] or cmd1[-1] == "/dev/null"

    # Pass 2
    cmd2 = build_encode_command(
        input_path=Path("/input.mp4"),
        output_part_path=Path("/out.webm.part"),
        start_us=0,
        duration_us=10_000_000,
        video_bps=3_000_000,
        pass_number=2,
        passlogfile=Path("/tmp/clip_0000"),
    )
    assert cmd2[cmd2.index("-pass") + 1] == "2"
    assert cmd2[cmd2.index("-passlogfile") + 1] == "/tmp/clip_0000"
    assert cmd2[-1] == "/out.webm.part"


def test_filename_defense_relative_path() -> None:
    cmd = build_encode_command(
        input_path=Path("my_video.mp4"),
        output_part_path=Path("out.webm.part"),
        start_us=0,
        duration_us=10_000_000,
        video_bps=3_000_000,
    )
    i_idx = cmd.index("-i")
    assert cmd[i_idx + 1] == "./my_video.mp4"
    assert cmd[-1] == "./out.webm.part"
