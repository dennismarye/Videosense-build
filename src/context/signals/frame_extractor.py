"""
Frame Extractor — extracts candidate thumbnail frames from video.

Strategy:
1. Extract frames at scene boundaries (most visually distinct moments)
2. Extract frames at regular intervals as fallback
3. Score frames by basic quality metrics (not AI — just sharpness/brightness)

Deterministic: same video → same frames.
"""

import logging
import os
import subprocess
from typing import List, Optional

from src.context.models import ThumbnailCandidate

logger = logging.getLogger(__name__)

# Number of thumbnail candidates to extract
DEFAULT_MAX_CANDIDATES = 10
# Minimum interval between candidate frames (seconds)
MIN_FRAME_INTERVAL = 2.0


def extract_thumbnail_candidates(
    video_path: str,
    output_dir: str,
    duration: float,
    scene_timestamps: Optional[List[float]] = None,
    max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> List[ThumbnailCandidate]:
    """
    Extract candidate thumbnail frames from a video.

    Prefers scene boundary frames, falls back to evenly-spaced extraction.
    """
    os.makedirs(output_dir, exist_ok=True)
    candidates = []

    # Strategy 1: Extract at scene boundaries
    if scene_timestamps and len(scene_timestamps) > 0:
        timestamps = scene_timestamps[:max_candidates]
        for i, ts in enumerate(timestamps):
            frame_path = _extract_frame_at(video_path, ts, output_dir, f"scene_{i}")
            if frame_path:
                candidates.append(ThumbnailCandidate(
                    timestamp=ts,
                    score=0.0,  # Scored later
                    reasons=["scene_boundary"],
                    frame_path=frame_path,
                ))

    # Strategy 2: Fill remaining slots with evenly-spaced frames
    remaining = max_candidates - len(candidates)
    if remaining > 0 and duration > 0:
        interval = max(duration / (remaining + 1), MIN_FRAME_INTERVAL)
        existing_timestamps = {c.timestamp for c in candidates}

        ts = interval
        while ts < duration and len(candidates) < max_candidates:
            # Skip if too close to an existing candidate
            if not any(abs(ts - et) < MIN_FRAME_INTERVAL for et in existing_timestamps):
                idx = len(candidates)
                frame_path = _extract_frame_at(video_path, ts, output_dir, f"interval_{idx}")
                if frame_path:
                    candidates.append(ThumbnailCandidate(
                        timestamp=ts,
                        score=0.0,
                        reasons=["interval"],
                        frame_path=frame_path,
                    ))
                    existing_timestamps.add(ts)
            ts += interval

    # Score all candidates
    for candidate in candidates:
        candidate.score = _score_frame(candidate.frame_path)

    # Sort by score descending
    candidates.sort(key=lambda c: c.score, reverse=True)

    logger.info(f"Extracted {len(candidates)} thumbnail candidates")
    return candidates


def _extract_frame_at(
    video_path: str,
    timestamp: float,
    output_dir: str,
    label: str,
) -> Optional[str]:
    """Extract a single frame at the given timestamp."""
    try:
        output_path = os.path.join(output_dir, f"thumb_{label}_{timestamp:.2f}.jpg")

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",  # High quality JPEG
            output_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=15,
        )

        if result.returncode == 0 and os.path.exists(output_path):
            return output_path
        return None

    except Exception as e:
        logger.debug(f"Frame extraction at {timestamp}s failed: {e}")
        return None


def _score_frame(frame_path: Optional[str]) -> float:
    """
    Score a frame by basic quality metrics.

    Uses file size as a proxy for visual complexity/sharpness —
    JPEG compresses flat/blurry frames much smaller than detailed ones.
    """
    if not frame_path or not os.path.exists(frame_path):
        return 0.0

    try:
        file_size = os.path.getsize(frame_path)
        # Normalize: typical thumbnail JPEG is 20KB-200KB
        # Higher file size = more visual detail = better thumbnail
        score = min(file_size / 200_000, 1.0)
        return round(score, 3)
    except Exception:
        return 0.0
