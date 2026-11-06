"""Doctor tests against a mocked subprocess runner (FR-BEN-01)."""

from __future__ import annotations

import subprocess

from clipforge.cli.commands.doctor import collect, container_support

FFMPEG_VERSION = "ffmpeg version n9.0.2 Copyright (c) 2000-2026 the FFmpeg developers"
FFPROBE_VERSION = "ffprobe version n9.0.2 Copyright (c) 2000-2026 the FFmpeg developers"

ENCODERS = """\
 T.. libvpx-vp9  libvpx VP9
 T.. libopus     libopus Opus
"""
FILTERS = " ... vmaf  V->V       Compute the VMAF metric.\n"
HWACCELS = "Hardware acceleration methods:\n vaapi\n"
DEMUXERS = """\
Formats:
 D.. = Demuxing supported
 .E. = Muxing supported
 ..d = Is a device
 ---
 D   3dostr          3DO STR
 D   4xm             4X Technologies
 D   aa              Audible AA format files
 D   avi             AVI (Audio Video Interleaved)
 D   flv             FLV (Flash Video)
 D   matroska,webm   Matroska / WebM
 D   mov,mp4,m4a,3gp,3g2,jp2 QuickTime / MOV
 D   mpegts          MPEG-TS (MPEG-2 Transport Stream)
 D   ogg             Ogg
 D   wav             WAV / WAVE (Waveform Audio)
"""


class FakeRunner:
    """Substitute runner: canned stdout per tool subcommand, OSError for missing tools."""

    def __init__(self, missing: frozenset[str] = frozenset()) -> None:
        self._canned = {
            "ffmpeg -version": FFMPEG_VERSION,
            "ffprobe -version": FFPROBE_VERSION,
            "ffmpeg -hide_banner -encoders": ENCODERS,
            "ffmpeg -hide_banner -filters": FILTERS,
            "ffmpeg -hide_banner -hwaccels": HWACCELS,
            "ffmpeg -hide_banner -demuxers": DEMUXERS,
        }
        self._missing = missing

    def __call__(self, argv: list[str]) -> subprocess.CompletedProcess[str]:
        if argv[0] in self._missing:
            raise FileNotFoundError(argv[0])
        key = " ".join(argv)
        return subprocess.CompletedProcess(argv, 0, stdout=self._canned.get(key, ""), stderr="")


def test_full_stack_reports_everything_present() -> None:
    by_name = {c.name: c for c in collect(FakeRunner())}
    for name in ("ffmpeg", "ffprobe", "libvpx-vp9 encoder", "libopus encoder"):
        assert by_name[name].present, name
        assert by_name[name].required, name
    assert by_name["libvmaf filter"].present
    assert by_name["vaapi hwaccel"].present
    # Optional components stay optional
    assert not by_name["libvmaf filter"].required
    assert not by_name["vaapi hwaccel"].required


def test_missing_ffmpeg_marks_dependent_checks_absent() -> None:
    by_name = {c.name: c for c in collect(FakeRunner(missing=frozenset({"ffmpeg"})))}
    assert not by_name["ffmpeg"].present
    # Encoders, filters, and hwaccels cannot be checked without ffmpeg
    assert not by_name["libvpx-vp9 encoder"].present
    assert not by_name["libopus encoder"].present
    assert not by_name["libvmaf filter"].present
    assert not by_name["vaapi hwaccel"].present
    # ffprobe is a separate binary, so it is still there
    assert by_name["ffprobe"].present


def test_missing_ffprobe_is_required_and_reported() -> None:
    by_name = {c.name: c for c in collect(FakeRunner(missing=frozenset({"ffprobe"})))}
    assert not by_name["ffprobe"].present
    assert by_name["ffprobe"].required


def test_container_support_counts_and_matches() -> None:
    families, demuxer_count = container_support(FakeRunner())
    readable = {f.label: f.present for f in families}
    assert readable["mp4, mov, m4v"]
    assert readable["mkv, webm"]
    # The sample has 10 demuxer rows; the header and the D.. legend must not count
    assert demuxer_count == 10


def test_container_support_without_ffmpeg_reports_nothing() -> None:
    families, demuxer_count = container_support(FakeRunner(missing=frozenset({"ffmpeg"})))
    assert not any(f.present for f in families)
    assert demuxer_count == 0
