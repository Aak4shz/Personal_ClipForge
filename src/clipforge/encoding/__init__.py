"""FFmpeg argument building, profiles, supervised runs, and verification (Phase 4)."""

from clipforge.encoding.builder import build_clip_command, build_encode_command
from clipforge.encoding.profiles import (
    PROFILES,
    ProfileSettings,
    calculate_keyframe_interval,
    calculate_lag_in_frames,
    calculate_tile_columns,
    get_profile,
)
from clipforge.encoding.progress import ProgressFrame, parse_progress_chunk
from clipforge.encoding.runner import EncodeResult, run_encode
from clipforge.encoding.verify import ClipVerification, verify_clip

__all__ = [
    "PROFILES",
    "ClipVerification",
    "EncodeResult",
    "ProfileSettings",
    "ProgressFrame",
    "build_clip_command",
    "build_encode_command",
    "calculate_keyframe_interval",
    "calculate_lag_in_frames",
    "calculate_tile_columns",
    "get_profile",
    "parse_progress_chunk",
    "run_encode",
    "verify_clip",
]
