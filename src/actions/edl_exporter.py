"""
EDL Exporter — converts SuggestedClips to Edit Decision List format.

Supports three export targets:
  1. CMX 3600 EDL — standard interchange for NLEs (Premiere, Resolve, FCP)
  2. OpenCut timeline markers — JSON markers for the Circo editor fork
  3. FFmpeg extract commands — ready-to-run subprocess args for clip extraction

Each clip's aspect ratio drives the FFmpeg filter chain:
  - 16:9 (landscape): no crop, scale to 1920x1080
  - 9:16 (portrait): center crop to ih*9/16:ih, scale to 1080x1920
  - 1:1 (square): center crop to min(iw,ih):min(iw,ih), scale to 1080x1080
"""

from __future__ import annotations

import logging
import math
from typing import List

from src.context.models import ClipFormat, SuggestedClip

logger = logging.getLogger(__name__)


# ── Timecode Helper ──────────────────────────────────────────

def _seconds_to_timecode(seconds: float, fps: float = 24.0) -> str:
    """
    Convert float seconds to SMPTE timecode HH:MM:SS:FF.

    Args:
        seconds: Time in seconds (non-negative).
        fps: Frames per second for the frame count portion.

    Returns:
        Timecode string like "01:23:45:12".
    """
    if seconds < 0:
        seconds = 0.0

    total_frames = int(round(seconds * fps))

    frames_per_second = int(fps)
    ff = total_frames % frames_per_second
    total_seconds = total_frames // frames_per_second
    ss = total_seconds % 60
    total_minutes = total_seconds // 60
    mm = total_minutes % 60
    hh = total_minutes // 60

    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


# ── CMX 3600 EDL Export ─────────────────────────────────────

def export_edl(
    clips: List[SuggestedClip],
    video_id: str,
    fps: float = 24.0,
) -> str:
    """
    Export clips as a CMX 3600 EDL string.

    Each clip becomes one edit event with source in/out and record in/out.
    Record timecodes are sequential (each clip placed after the previous).

    Args:
        clips: List of SuggestedClip objects to include.
        video_id: Identifier for the source video (used in EDL title).
        fps: Frame rate for timecode calculation.

    Returns:
        Complete EDL file content as a string.
    """
    logger.info(f"Exporting EDL for video={video_id}, {len(clips)} clips, fps={fps}")

    lines: List[str] = [
        f"TITLE: Video Sense - {video_id}",
        f"FCM: NON-DROP FRAME",
        "",
    ]

    record_offset = 0.0  # running record position in seconds

    for idx, clip in enumerate(clips, start=1):
        duration = clip.end - clip.start
        if duration <= 0:
            logger.warning(
                f"Skipping clip {clip.clip_id}: non-positive duration "
                f"(start={clip.start}, end={clip.end})"
            )
            continue

        # Source timecodes
        src_in = _seconds_to_timecode(clip.start, fps)
        src_out = _seconds_to_timecode(clip.end, fps)

        # Record timecodes (sequential placement)
        rec_in = _seconds_to_timecode(record_offset, fps)
        rec_out = _seconds_to_timecode(record_offset + duration, fps)

        # Event number, padded to 3 digits
        event_num = f"{idx:03d}"

        # Standard CMX 3600 event line:
        # EVENT  REEL  TRACK  TRANSITION  SRC_IN  SRC_OUT  REC_IN  REC_OUT
        event_line = (
            f"{event_num}  AX       V     C        "
            f"{src_in} {src_out} {rec_in} {rec_out}"
        )
        lines.append(event_line)

        # Optional comment with clip metadata
        lines.append(
            f"* CLIP: {clip.clip_id}  "
            f"SCORE: {clip.score:.2f}  "
            f"FORMAT: {clip.format.value}"
        )
        if clip.rationale:
            lines.append(f"* RATIONALE: {clip.rationale}")
        lines.append("")

        record_offset += duration

    edl_content = "\n".join(lines)
    logger.debug(f"EDL generated: {len(lines)} lines, {len(clips)} events")
    return edl_content


# ── OpenCut Timeline Markers ────────────────────────────────

def export_timeline_markers(clips: List[SuggestedClip]) -> List[dict]:
    """
    Export clips as JSON-compatible timeline markers for the OpenCut editor.

    Color coding by score:
      - Red (#FF2F2F): score > 0.7 (high confidence)
      - Orange (#FF8C00): score > 0.4 (moderate confidence)
      - Gray (#9CA3AF): score <= 0.4 (low confidence)

    Args:
        clips: List of SuggestedClip objects.

    Returns:
        List of marker dictionaries ready for JSON serialization.
    """
    logger.info(f"Exporting {len(clips)} timeline markers for OpenCut")

    markers: List[dict] = []

    for clip in clips:
        # Determine color based on score thresholds
        if clip.score > 0.7:
            color = "#FF2F2F"
        elif clip.score > 0.4:
            color = "#FF8C00"
        else:
            color = "#9CA3AF"

        marker = {
            "id": clip.clip_id,
            "start": clip.start,
            "end": clip.end,
            "score": clip.score,
            "label": clip.rationale or "",
            "format": clip.format.value,
            "color": color,
        }
        markers.append(marker)

    logger.debug(f"Generated {len(markers)} timeline markers")
    return markers


# ── FFmpeg Command Generation ───────────────────────────────

def generate_ffmpeg_extract_cmd(
    clip: SuggestedClip,
    source_path: str,
    output_path: str,
) -> List[str]:
    """
    Build an FFmpeg command to extract and reformat a single clip.

    Strategy:
      - Uses -ss before -i for fast input seeking
      - Duration via -t (avoids re-encoding unnecessary frames)
      - Video filter chain depends on clip format (aspect ratio)
      - Audio is stream-copied (-c:a copy) for speed
      - Video is re-encoded with libx264 -preset fast for compatibility

    Args:
        clip: The SuggestedClip defining time range and target format.
        source_path: Path to the source video file.
        output_path: Destination path for the extracted clip.

    Returns:
        FFmpeg command as a list of strings (suitable for subprocess.run).
    """
    duration = clip.end - clip.start
    if duration <= 0:
        logger.warning(
            f"Clip {clip.clip_id} has non-positive duration; "
            f"command will produce empty output"
        )

    # Build the video filter chain based on target format
    vf = _build_video_filter(clip.format)

    cmd = [
        "ffmpeg",
        "-y",                       # overwrite output
        "-ss", str(clip.start),     # seek to start (before -i for fast seek)
        "-i", source_path,          # input file
        "-t", str(duration),        # duration to extract
        "-vf", vf,                  # video filter chain
        "-c:v", "libx264",          # re-encode video
        "-preset", "fast",          # encoding speed
        "-c:a", "copy",             # copy audio stream
        output_path,
    ]

    logger.debug(
        f"FFmpeg cmd for clip {clip.clip_id} "
        f"({clip.format.value}): {' '.join(cmd)}"
    )
    return cmd


def _build_video_filter(fmt: ClipFormat) -> str:
    """
    Build the FFmpeg -vf filter string for the target aspect ratio.

    - PORTRAIT (9:16): center crop to 9:16, then scale to 1080x1920
    - SQUARE (1:1): center crop to square, then scale to 1080x1080
    - LANDSCAPE (16:9): no crop (passthrough), scale to 1920x1080
    """
    if fmt == ClipFormat.PORTRAIT:
        # Center-crop to 9:16 aspect ratio, then scale
        return "crop=ih*9/16:ih,scale=1080:1920"
    elif fmt == ClipFormat.SQUARE:
        # Center-crop to square, then scale
        return "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080"
    else:
        # Landscape: no crop needed, just scale
        return "scale=1920:1080"
