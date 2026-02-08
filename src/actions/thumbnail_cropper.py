"""
Thumbnail Crop Recommender — generates crop regions per platform aspect ratio.

Takes ranked thumbnail candidates (from V1 thumbnail_ranker) and recommends
crop regions for each platform's target aspect ratio:

  - 16:9 (landscape) — YouTube, Circo
  - 9:16 (portrait) — TikTok, Instagram Reels
  - 1:1 (square) — general social
  - 4:5 (portrait-ish) — Instagram feed

For each thumbnail × aspect ratio combination:
  1. Calculate the largest crop region that fits the aspect ratio
  2. Center the crop (heuristic: center of frame or AI-suggested center)
  3. Score the crop via AI service (face centering, rule-of-thirds, contrast)
  4. Return best crop per platform per thumbnail

No actual re-encoding happens here — this is crop metadata only.
FFmpeg crop execution is deferred to V2.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from src.context.models import (
    CropRegion,
    Platform,
    ThumbnailCandidate,
    ThumbnailCrop,
    VideoContext,
)

logger = logging.getLogger(__name__)

# ── Aspect ratio targets per platform ────────────────────────

PLATFORM_ASPECT_RATIOS: dict[Platform, str] = {
    Platform.CIRCO: "16:9",
    Platform.YOUTUBE_SHORTS: "9:16",
    Platform.TIKTOK: "9:16",
    Platform.INSTAGRAM_REELS: "9:16",
    Platform.X: "16:9",
}

# All supported aspect ratios with their width:height ratios
ASPECT_RATIO_VALUES: dict[str, tuple[int, int]] = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
    "4:5": (4, 5),
}

# Default frame dimensions (overridden by context.overall_quality if available)
DEFAULT_FRAME_WIDTH = 1920
DEFAULT_FRAME_HEIGHT = 1080

# Max thumbnails to process
MAX_THUMBNAILS = 5


# ── Public API ───────────────────────────────────────────────

async def recommend_crops(
    context: VideoContext,
    ai_service,
    platforms: Optional[List[Platform]] = None,
) -> List[ThumbnailCrop]:
    """
    Generate thumbnail crop recommendations for each platform.

    Args:
        context: VideoContext with thumbnail_candidates from V1.
        ai_service: AIService (Protocol) with score_thumbnail_crop method.
        platforms: Platforms to generate for. Defaults to all platforms.

    Returns:
        List of ThumbnailCrop recommendations.
    """
    if platforms is None:
        platforms = list(Platform)

    candidates = context.thumbnail_candidates[:MAX_THUMBNAILS]

    if not candidates:
        logger.info("No thumbnail candidates to crop; returning empty list")
        return []

    # Determine frame dimensions
    frame_w, frame_h = _get_frame_dimensions(context)

    logger.info(
        f"Recommending crops for {len(candidates)} thumbnails × "
        f"{len(platforms)} platforms (frame={frame_w}x{frame_h}, "
        f"video={context.video_id})"
    )

    crops: List[ThumbnailCrop] = []

    for idx, candidate in enumerate(candidates):
        for platform in platforms:
            aspect_ratio = PLATFORM_ASPECT_RATIOS.get(platform, "16:9")
            crop_region = _compute_crop(frame_w, frame_h, aspect_ratio)

            # Score via AI service
            score = await _score_crop(
                ai_service, candidate.frame_path, crop_region
            )

            crops.append(ThumbnailCrop(
                thumbnail_index=idx,
                platform=platform,
                crop=crop_region,
                score=score,
            ))

    logger.info(
        f"Crop recommendation complete: {len(crops)} crops "
        f"for video={context.video_id}"
    )

    return crops


# ── Private helpers ──────────────────────────────────────────

def _get_frame_dimensions(context: VideoContext) -> tuple[int, int]:
    """Extract frame dimensions from context or use defaults."""
    if context.overall_quality and context.overall_quality.resolution:
        try:
            parts = context.overall_quality.resolution.split("x")
            if len(parts) == 2:
                return int(parts[0]), int(parts[1])
        except (ValueError, IndexError):
            pass
    return DEFAULT_FRAME_WIDTH, DEFAULT_FRAME_HEIGHT


def _compute_crop(
    frame_w: int,
    frame_h: int,
    aspect_ratio: str,
) -> CropRegion:
    """
    Compute the largest centered crop region for the given aspect ratio
    within the frame bounds.
    """
    ratio_w, ratio_h = ASPECT_RATIO_VALUES.get(aspect_ratio, (16, 9))

    # Calculate maximum crop size that fits within frame
    if frame_w / frame_h > ratio_w / ratio_h:
        # Frame is wider than target — constrained by height
        crop_h = frame_h
        crop_w = int(frame_h * ratio_w / ratio_h)
    else:
        # Frame is taller than target — constrained by width
        crop_w = frame_w
        crop_h = int(frame_w * ratio_h / ratio_w)

    # Clamp to frame bounds
    crop_w = min(crop_w, frame_w)
    crop_h = min(crop_h, frame_h)

    # Center the crop
    x = (frame_w - crop_w) // 2
    y = (frame_h - crop_h) // 2

    return CropRegion(
        x=x,
        y=y,
        width=crop_w,
        height=crop_h,
        aspect_ratio=aspect_ratio,
        frame_width=frame_w,
        frame_height=frame_h,
    )


async def _score_crop(
    ai_service,
    frame_path: Optional[str],
    crop: CropRegion,
) -> float:
    """Score a crop region via AI service, falling back to heuristic."""
    if ai_service is None:
        return _heuristic_score(crop)

    try:
        score = await ai_service.score_thumbnail_crop(frame_path or "", crop)
        return round(min(max(score, 0.0), 1.0), 3)
    except Exception as e:
        logger.warning(f"AI crop scoring failed, using heuristic: {e}")
        return _heuristic_score(crop)


def _heuristic_score(crop: CropRegion) -> float:
    """
    Simple heuristic: larger crops relative to frame get higher scores.
    Center-weighted crops score better.
    """
    # Area ratio: how much of the frame does the crop cover?
    frame_area = crop.frame_width * crop.frame_height
    crop_area = crop.width * crop.height
    area_ratio = crop_area / max(frame_area, 1)

    # Center penalty: how far is the crop center from frame center?
    crop_cx = crop.x + crop.width / 2
    crop_cy = crop.y + crop.height / 2
    frame_cx = crop.frame_width / 2
    frame_cy = crop.frame_height / 2

    # Normalized distance from center (0 = perfect center, 1 = corner)
    dx = abs(crop_cx - frame_cx) / max(crop.frame_width / 2, 1)
    dy = abs(crop_cy - frame_cy) / max(crop.frame_height / 2, 1)
    center_penalty = (dx + dy) / 2

    score = 0.7 * area_ratio + 0.3 * (1.0 - center_penalty)
    return round(min(max(score, 0.0), 1.0), 3)
