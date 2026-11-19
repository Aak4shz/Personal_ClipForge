"""Compatibility report: preserved, converted, or applied verdicts (FR-PRO-03).

Each input stream gets a line-by-line verdict. The bpp feasibility line is
deferred to Phase 3 (planner/feasibility.py); here we only report what the
probe tells us about codec/container support.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from clipforge.probe.metadata import AudioStreamInfo, FormatInfo, ProbeData, VideoStreamInfo

Verdict = Literal["preserved", "converted", "applied", "rejected"]


@dataclass(frozen=True)
class StreamVerdict:
    """One stream's compatibility outcome."""

    index: int
    codec_type: Literal["video", "audio"]
    input_codec: str
    output_codec: str
    verdict: Verdict
    reason: str


@dataclass(frozen=True)
class ContainerVerdict:
    """Container-level compatibility."""

    input_format: str
    output_format: Literal["webm"]
    verdict: Verdict
    reason: str


@dataclass(frozen=True)
class CompatibilityReport:
    """Full compatibility report for one input file."""

    container: ContainerVerdict
    video_verdicts: list[StreamVerdict]
    audio_verdicts: list[StreamVerdict]

    @property
    def has_video(self) -> bool:
        return bool(self.video_verdicts)

    @property
    def has_audio(self) -> bool:
        return bool(self.audio_verdicts)


# Target codecs are fixed by the blueprint
_TARGET_VIDEO_CODEC = "libvpx-vp9"
_TARGET_AUDIO_CODEC = "libopus"
_TARGET_CONTAINER = "webm"


def _map_pixel_format(pix_fmt: str, bits: int | None) -> tuple[str, str | None]:
    """Map input pixel format to VP9 target (FR-PRO-05).

    Returns (target_pix_fmt, warning_or_note).
    """
    is_10bit = (bits == 10) or "10" in pix_fmt or "12" in pix_fmt or "16" in pix_fmt
    is_subsampled_higher = any(x in pix_fmt for x in ("422", "444", "rgb", "bgr", "gbr"))

    if is_10bit:
        target = "yuv420p10le"
        note = "10-bit -> yuv420p10le (VP9 Profile 2; warning: limited device playback)"
        if is_subsampled_higher:
            note += "; downsample chroma to 4:2:0"
        return target, note

    target = "yuv420p"
    if is_subsampled_higher:
        return target, "downsample chroma to 4:2:0 (yuv420p, VP9 Profile 0)"
    return target, None


def _rotation_note(v: VideoStreamInfo) -> str | None:
    """Note rotation baked into pixels and display resolution swap (FR-PRO-04)."""
    if v.rotation != 0:
        return (
            f"rotation {v.rotation}° baked into pixels: "
            f"{v.width}x{v.height} -> {v.display_width}x{v.display_height} upright"
        )
    return None


def _hdr_warning(v: VideoStreamInfo) -> str | None:
    """Detect HDR sources and warn about --hdr keep policy (FR-PRO-06)."""
    is_hdr_transfer = v.color_transfer in ("smpte2084", "arib-std-b67")
    is_wide_gamut = bool(
        (v.color_primaries and "bt2020" in v.color_primaries)
        or (v.color_space and "bt2020" in v.color_space)
    )
    if is_hdr_transfer or is_wide_gamut:
        return "HDR keep: color metadata preserved (warning: tonemap coming in later version)"
    return None


def _video_verdict(v: VideoStreamInfo) -> StreamVerdict:
    codec = v.codec_name
    _, pix_note = _map_pixel_format(v.pix_fmt, v.bits_per_raw_sample)
    rot_note = _rotation_note(v)
    hdr_note = _hdr_warning(v)

    notes: list[str] = []
    # VP9 decode is widely supported; the encoder is libvpx-vp9 (checked by doctor)
    if codec in ("vp9", "libvpx-vp9"):
        notes.append("already VP9; re-encode required for splitting (RULE-07)")
        verdict: Verdict = "applied" if rot_note else "preserved"
    elif codec in ("h264", "hevc", "h265", "mpeg4", "mpeg2video", "vc1", "av1", "vp8"):
        notes.append(f"decode {codec} -> encode {_TARGET_VIDEO_CODEC}")
        verdict = "converted"
    else:
        notes.append(f"decode {codec} -> encode {_TARGET_VIDEO_CODEC} (untested codec)")
        verdict = "converted"

    if rot_note:
        notes.append(rot_note)
    if pix_note:
        notes.append(pix_note)
    if hdr_note:
        notes.append(hdr_note)

    return StreamVerdict(
        index=v.index,
        codec_type="video",
        input_codec=codec,
        output_codec=_TARGET_VIDEO_CODEC,
        verdict=verdict,
        reason="; ".join(notes),
    )


def _audio_verdict(a: AudioStreamInfo) -> StreamVerdict:
    codec = a.codec_name
    notes: list[str] = []
    if codec in ("opus", "libopus"):
        notes.append("already Opus; re-encode required for splitting")
        verdict: Verdict = "preserved"
    elif codec in ("aac", "mp3", "flac", "vorbis", "pcm_s16le", "pcm_s24le", "ac3", "eac3"):
        notes.append(f"decode {codec} -> encode {_TARGET_AUDIO_CODEC}")
        verdict = "converted"
    else:
        notes.append(f"decode {codec} -> encode {_TARGET_AUDIO_CODEC} (untested codec)")
        verdict = "converted"

    if a.channels and a.channels > 2:
        layout = f" ({a.channel_layout})" if a.channel_layout else ""
        notes.append(f"{a.channels}ch{layout} audio")
    if a.sample_rate and a.sample_rate != 48000:
        notes.append(f"resample {a.sample_rate} Hz -> 48000 Hz")

    return StreamVerdict(
        index=a.index,
        codec_type="audio",
        input_codec=codec,
        output_codec=_TARGET_AUDIO_CODEC,
        verdict=verdict,
        reason="; ".join(notes),
    )


def _container_verdict(f: FormatInfo) -> ContainerVerdict:
    # WebM/Matroska input -> webM output is a natural mapping
    input_fmt = f.format_name.lower()
    if "matroska" in input_fmt or "webm" in input_fmt:
        return ContainerVerdict(
            input_format=f.format_name,
            output_format="webm",
            verdict="preserved",
            reason="Matroska/WebM input -> WebM output (container structure similar)",
        )
    # MP4/MOV -> WebM is common and well supported
    if any(x in input_fmt for x in ("mp4", "mov", "m4v", "quicktime")):
        return ContainerVerdict(
            input_format=f.format_name,
            output_format="webm",
            verdict="converted",
            reason=f"{f.format_name} -> webm (remux + re-encode)",
        )
    # Everything else: we'll try
    return ContainerVerdict(
        input_format=f.format_name,
        output_format="webm",
        verdict="converted",
        reason=f"{f.format_name} -> webm (untested container)",
    )


def build_report(probe: ProbeData) -> CompatibilityReport:
    """Build the compatibility report from normalized ProbeData (pure function)."""
    return CompatibilityReport(
        container=_container_verdict(probe.format),
        video_verdicts=[_video_verdict(v) for v in probe.video_streams],
        audio_verdicts=[_audio_verdict(a) for a in probe.audio_streams],
    )
