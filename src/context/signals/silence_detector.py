"""
Silence Detector — uses FFmpeg's silencedetect filter.

Identifies silent regions and speech regions in the audio track.
Deterministic: same video → same results.
"""

import logging
import re
import subprocess
from typing import List, Tuple

from src.context.models import TimeRange, SpeechRegion

logger = logging.getLogger(__name__)

# Silence threshold in dB (below this is "silence")
DEFAULT_NOISE_DB = -30
# Minimum silence duration in seconds
DEFAULT_MIN_DURATION = 0.5


def detect_silence(
    video_path: str,
    noise_db: float = DEFAULT_NOISE_DB,
    min_duration: float = DEFAULT_MIN_DURATION,
) -> List[TimeRange]:
    """
    Detect silent regions using FFmpeg's silencedetect filter.

    Returns a list of TimeRange objects representing silence.
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-af", f"silencedetect=noise={noise_db}dB:d={min_duration}",
            "-f", "null",
            "-",
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )

        # silencedetect outputs to stderr
        output = result.stderr
        silence_regions = _parse_silence_output(output)

        logger.info(f"Detected {len(silence_regions)} silence regions in {video_path}")
        return silence_regions

    except subprocess.TimeoutExpired:
        logger.error(f"Silence detection timed out for {video_path}")
        return []
    except Exception as e:
        logger.error(f"Silence detection failed: {e}")
        return []


def detect_speech_regions(
    video_path: str,
    total_duration: float,
    noise_db: float = DEFAULT_NOISE_DB,
    min_duration: float = DEFAULT_MIN_DURATION,
) -> Tuple[List[TimeRange], List[SpeechRegion]]:
    """
    Detect both silence and speech regions.

    Speech regions are the inverse of silence regions within the video duration.
    Returns (silence_regions, speech_regions).
    """
    silence_regions = detect_silence(video_path, noise_db, min_duration)

    # Invert silence to get speech regions
    speech_regions = []
    prev_end = 0.0

    for silence in silence_regions:
        if silence.start > prev_end + 0.1:  # Min gap to count as speech
            speech_regions.append(SpeechRegion(
                start=prev_end,
                end=silence.start,
            ))
        prev_end = silence.end

    # Final speech region (from last silence to end of video)
    if total_duration > prev_end + 0.1:
        speech_regions.append(SpeechRegion(
            start=prev_end,
            end=total_duration,
        ))

    logger.info(f"Detected {len(speech_regions)} speech regions")
    return silence_regions, speech_regions


def calculate_silence_ratio(
    silence_regions: List[TimeRange],
    total_duration: float,
) -> float:
    """Calculate what fraction of the video is silent."""
    if total_duration <= 0:
        return 0.0
    total_silence = sum(r.end - r.start for r in silence_regions)
    return min(total_silence / total_duration, 1.0)


def _parse_silence_output(output: str) -> List[TimeRange]:
    """Parse FFmpeg silencedetect output into TimeRange objects."""
    regions = []

    # Pattern: silence_start: 1.234 | silence_end: 5.678 | silence_duration: 4.444
    start_pattern = re.compile(r"silence_start:\s*([\d.]+)")
    end_pattern = re.compile(r"silence_end:\s*([\d.]+)")

    starts = [float(m.group(1)) for m in start_pattern.finditer(output)]
    ends = [float(m.group(1)) for m in end_pattern.finditer(output)]

    for start, end in zip(starts, ends):
        regions.append(TimeRange(start=start, end=end))

    return regions
