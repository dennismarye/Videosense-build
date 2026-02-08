"""
Scene Detector — uses FFmpeg's scene filter to find scene boundaries.

Deterministic: same video → same scenes every time.
"""

import json
import logging
import subprocess
from typing import List

from src.context.models import Scene

logger = logging.getLogger(__name__)

# Threshold for scene change detection (0.0-1.0, lower = more sensitive)
DEFAULT_THRESHOLD = 0.3


def detect_scenes(video_path: str, threshold: float = DEFAULT_THRESHOLD) -> List[Scene]:
    """
    Detect scene boundaries using FFmpeg's select filter with scene detection.

    Uses the 'scene' metric from the select filter which measures
    the difference between consecutive frames (0.0 = identical, 1.0 = completely different).
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-show_frames",
            "-select_streams", "v:0",
            "-print_format", "json",
            "-f", "lavfi",
            f"movie={video_path},select='gt(scene\\,{threshold})'",
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0:
            # Fallback: use simpler scene detection via showinfo
            return _detect_scenes_fallback(video_path, threshold)

        data = json.loads(result.stdout)
        frames = data.get("frames", [])

        scenes = []
        prev_time = 0.0

        for frame in frames:
            pts_time = float(frame.get("pts_time", 0))
            score = float(frame.get("tags", {}).get("lavfi.scene_score", 0))

            if pts_time > 0:
                scenes.append(Scene(
                    start=prev_time,
                    end=pts_time,
                    confidence=min(score, 1.0),
                ))
                prev_time = pts_time

        logger.info(f"Detected {len(scenes)} scenes in {video_path}")
        return scenes

    except subprocess.TimeoutExpired:
        logger.error(f"Scene detection timed out for {video_path}")
        return _detect_scenes_fallback(video_path, threshold)
    except Exception as e:
        logger.error(f"Scene detection failed: {e}")
        return _detect_scenes_fallback(video_path, threshold)


def _detect_scenes_fallback(video_path: str, threshold: float) -> List[Scene]:
    """
    Fallback scene detection using ffprobe showinfo filter.

    Simpler but more reliable approach: probe all video frames
    and look for large pixel difference scores.
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-select_streams", "v:0",
            "-show_entries", "frame=pts_time,pict_type",
            "-print_format", "json",
            video_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0:
            logger.warning("Fallback scene detection also failed")
            return []

        data = json.loads(result.stdout)
        frames = data.get("frames", [])

        # Use I-frames (keyframes) as scene boundaries
        scenes = []
        prev_time = 0.0

        for frame in frames:
            pts_time = float(frame.get("pts_time", 0))
            pict_type = frame.get("pict_type", "")

            if pict_type == "I" and pts_time > prev_time + 1.0:
                scenes.append(Scene(
                    start=prev_time,
                    end=pts_time,
                    confidence=0.5,  # Lower confidence for keyframe-based
                ))
                prev_time = pts_time

        logger.info(f"Fallback detected {len(scenes)} scenes (keyframe-based)")
        return scenes

    except Exception as e:
        logger.error(f"Fallback scene detection failed: {e}")
        return []
