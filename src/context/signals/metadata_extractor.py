"""
Metadata Extractor — uses FFprobe for video container/stream metadata.

Extracts:
- Duration, resolution, FPS, codec
- File size, container format
- Audio stream presence

Deterministic: same video → same results.
"""

import json
import logging
import os
import subprocess
from typing import Dict, Any, Optional

from src.context.models import OverallQuality, QualityLevel

logger = logging.getLogger(__name__)


def extract_metadata(video_path: str) -> Dict[str, Any]:
    """
    Extract video metadata using ffprobe.

    Returns a dict with: duration, width, height, fps, codec, has_audio,
    file_size, container_format.
    """
    metadata = {
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "fps": 0.0,
        "codec": None,
        "has_audio": False,
        "file_size": 0,
        "container_format": None,
    }

    try:
        metadata["file_size"] = os.path.getsize(video_path)
    except Exception:
        pass

    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-print_format", "json",
            "-show_format",
            "-show_streams",
            video_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30,
        )

        if result.returncode != 0:
            logger.error(f"ffprobe failed for {video_path}")
            return metadata

        data = json.loads(result.stdout)

        # Format-level metadata
        fmt = data.get("format", {})
        metadata["duration"] = float(fmt.get("duration", 0))
        metadata["container_format"] = fmt.get("format_name")

        # Stream-level metadata
        for stream in data.get("streams", []):
            codec_type = stream.get("codec_type")

            if codec_type == "video":
                metadata["width"] = int(stream.get("width", 0))
                metadata["height"] = int(stream.get("height", 0))
                metadata["codec"] = stream.get("codec_name")

                # Parse FPS from r_frame_rate (e.g., "30000/1001")
                r_frame_rate = stream.get("r_frame_rate", "0/1")
                try:
                    num, den = r_frame_rate.split("/")
                    if int(den) > 0:
                        metadata["fps"] = round(int(num) / int(den), 2)
                except (ValueError, ZeroDivisionError):
                    pass

            elif codec_type == "audio":
                metadata["has_audio"] = True

        logger.info(
            f"Metadata: {metadata['width']}x{metadata['height']} "
            f"@ {metadata['fps']}fps, {metadata['duration']:.1f}s, "
            f"codec={metadata['codec']}, audio={metadata['has_audio']}"
        )
        return metadata

    except subprocess.TimeoutExpired:
        logger.error(f"ffprobe timed out for {video_path}")
        return metadata
    except Exception as e:
        logger.error(f"Metadata extraction failed: {e}")
        return metadata


def build_quality_from_metadata(metadata: Dict[str, Any]) -> OverallQuality:
    """
    Build an OverallQuality assessment from raw metadata.

    Scoring heuristic (V0 — no AI, just technical quality):
    - Resolution contributes 40 points
    - FPS contributes 20 points
    - Audio presence contributes 20 points
    - Duration contributes 20 points (penalizes very short or very long)
    """
    score = 0
    issues = []

    # Resolution scoring (40 pts)
    height = metadata.get("height", 0)
    width = metadata.get("width", 0)
    resolution = f"{width}x{height}" if width and height else None

    if height >= 1080:
        score += 40
    elif height >= 720:
        score += 30
    elif height >= 480:
        score += 20
        issues.append("low_resolution")
    elif height > 0:
        score += 10
        issues.append("very_low_resolution")
    else:
        issues.append("unknown_resolution")

    # FPS scoring (20 pts)
    fps = metadata.get("fps", 0)
    if fps >= 30:
        score += 20
    elif fps >= 24:
        score += 15
    elif fps > 0:
        score += 10
        issues.append("low_fps")
    else:
        issues.append("unknown_fps")

    # Audio scoring (20 pts)
    has_audio = metadata.get("has_audio", False)
    if has_audio:
        score += 20
    else:
        issues.append("no_audio")

    # Duration scoring (20 pts)
    duration = metadata.get("duration", 0)
    if 10 <= duration <= 3600:
        score += 20
    elif 3 <= duration <= 7200:
        score += 15
    elif duration > 0:
        score += 10
        if duration < 3:
            issues.append("very_short")
        else:
            issues.append("very_long")
    else:
        issues.append("unknown_duration")

    # Map to level
    if score >= 80:
        level = QualityLevel.EXCELLENT
    elif score >= 60:
        level = QualityLevel.GOOD
    elif score >= 40:
        level = QualityLevel.FAIR
    else:
        level = QualityLevel.POOR

    return OverallQuality(
        score=score,
        level=level,
        resolution=resolution,
        fps=fps if fps > 0 else None,
        codec=metadata.get("codec"),
        has_audio=has_audio,
        issues=issues,
    )
