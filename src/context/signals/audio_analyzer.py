"""
Audio Analyzer — uses FFmpeg's loudnorm/volumedetect for energy analysis.

Extracts:
- Overall audio energy (loudness)
- Peak and mean volume
- Audio clarity estimate (based on dynamic range)

Deterministic: same video → same results.
"""

import json
import logging
import re
import subprocess
from typing import Dict, Any, Optional

from src.context.models import AudioTone

logger = logging.getLogger(__name__)


def analyze_audio(video_path: str) -> Optional[AudioTone]:
    """
    Analyze audio characteristics using FFmpeg volumedetect.

    Returns AudioTone with energy and clarity scores.
    """
    try:
        volume_stats = _get_volume_stats(video_path)
        if not volume_stats:
            return AudioTone(energy=0.0, sentiment=0.0, clarity=0.0)

        mean_volume = volume_stats.get("mean_volume", -91.0)
        max_volume = volume_stats.get("max_volume", -91.0)

        # Energy: map mean volume from dB to 0-1 scale
        # -91 dB (silence) → 0.0, -10 dB (loud) → 1.0
        energy = max(0.0, min(1.0, (mean_volume + 91.0) / 81.0))

        # Clarity: based on dynamic range (difference between peak and mean)
        # Wider dynamic range = clearer audio (not compressed to a wall)
        dynamic_range = abs(max_volume - mean_volume)
        # Good dynamic range is 10-20 dB
        clarity = max(0.0, min(1.0, dynamic_range / 20.0))

        # Sentiment: neutral by default (requires AI for real analysis)
        sentiment = 0.0

        tone = AudioTone(
            energy=round(energy, 3),
            sentiment=sentiment,
            clarity=round(clarity, 3),
        )

        logger.info(
            f"Audio analysis: energy={tone.energy}, clarity={tone.clarity}, "
            f"mean={mean_volume:.1f}dB, peak={max_volume:.1f}dB"
        )
        return tone

    except Exception as e:
        logger.error(f"Audio analysis failed: {e}")
        return None


def _get_volume_stats(video_path: str) -> Optional[Dict[str, float]]:
    """Run FFmpeg volumedetect filter and parse output."""
    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-af", "volumedetect",
            "-f", "null",
            "-",
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60,
        )

        output = result.stderr

        stats = {}
        mean_match = re.search(r"mean_volume:\s*([-\d.]+)\s*dB", output)
        max_match = re.search(r"max_volume:\s*([-\d.]+)\s*dB", output)

        if mean_match:
            stats["mean_volume"] = float(mean_match.group(1))
        if max_match:
            stats["max_volume"] = float(max_match.group(1))

        return stats if stats else None

    except subprocess.TimeoutExpired:
        logger.error(f"Volume detection timed out for {video_path}")
        return None
    except Exception as e:
        logger.error(f"Volume detection failed: {e}")
        return None


def has_audio_stream(video_path: str) -> bool:
    """Check if the video has an audio stream at all."""
    try:
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-print_format", "json",
            video_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )

        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        return len(streams) > 0

    except Exception:
        return False
