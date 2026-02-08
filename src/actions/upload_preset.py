"""
Upload Preset Builder — assembles ready-to-publish presets per platform.

Bundles video format + metadata + constraints into a single UploadPreset
artifact that represents a "one-click publish" target.

For each platform bundle (from V1.1):
  1. Select best title variant for that platform
  2. Select best description variant for that platform
  3. Attach matching hashtag set
  4. Attach matching thumbnail crop (if available)
  5. Set format constraints from platform defaults

UploadPreset.ready is a derived @property — True only when all required
fields are populated and export_path exists. This is never manually set.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.context.models import (
    ClipFormat,
    ContentVariants,
    DescriptionVariant,
    HashtagSet,
    Platform,
    PlatformBundle,
    ThumbnailCrop,
    TitleVariant,
    UploadPreset,
    VideoContext,
)

logger = logging.getLogger(__name__)

# ── Platform format defaults ─────────────────────────────────

PLATFORM_FORMATS: Dict[Platform, dict] = {
    Platform.CIRCO: {
        "aspect_ratio": "16:9",
        "max_duration": 60.0,
        "resolution": "1920x1080",
    },
    Platform.TIKTOK: {
        "aspect_ratio": "9:16",
        "max_duration": 60.0,
        "resolution": "1080x1920",
    },
    Platform.INSTAGRAM_REELS: {
        "aspect_ratio": "9:16",
        "max_duration": 90.0,
        "resolution": "1080x1920",
    },
    Platform.X: {
        "aspect_ratio": "16:9",
        "max_duration": 140.0,
        "resolution": "1920x1080",
    },
    Platform.YOUTUBE_SHORTS: {
        "aspect_ratio": "9:16",
        "max_duration": 60.0,
        "resolution": "1080x1920",
    },
}


# ── Public API ───────────────────────────────────────────────

async def build_upload_presets(
    context: VideoContext,
) -> List[UploadPreset]:
    """
    Build upload presets from the current VideoContext state.

    Assembles one preset per platform bundle, selecting the best available
    title, description, hashtags, and thumbnail crop for each platform.

    Args:
        context: VideoContext with platform_bundles, content_variants,
                 thumbnail_crops populated from prior pipeline steps.

    Returns:
        List of UploadPreset objects. Each preset's `.ready` property
        indicates whether all required metadata is populated.
    """
    bundles = context.platform_bundles

    if not bundles:
        logger.info("No platform bundles to build presets for; returning empty list")
        return []

    logger.info(
        f"Building upload presets for {len(bundles)} platform bundles "
        f"(video={context.video_id})"
    )

    # Build lookup indices for efficient matching
    titles_by_platform = _index_titles(context.content_variants)
    descriptions_by_platform = _index_descriptions(context.content_variants)
    hashtags_by_platform = _index_hashtags(context)
    crops_by_platform = _index_crops(context.thumbnail_crops)

    presets: List[UploadPreset] = []

    for bundle in bundles:
        platform = bundle.platform
        fmt = PLATFORM_FORMATS.get(platform, PLATFORM_FORMATS[Platform.CIRCO])

        preset = UploadPreset(
            platform=platform,
            teaser_id=bundle.teaser_id,
            format="mp4",
            aspect_ratio=fmt["aspect_ratio"],
            max_duration=fmt["max_duration"],
            resolution=fmt["resolution"],
            title=titles_by_platform.get(platform),
            description=descriptions_by_platform.get(platform),
            hashtags=hashtags_by_platform.get(platform),
            thumbnail=crops_by_platform.get(platform),
            export_path=bundle.output_path if bundle.exported else None,
        )
        presets.append(preset)

    ready_count = sum(1 for p in presets if p.ready)
    logger.info(
        f"Built {len(presets)} upload presets ({ready_count} ready) "
        f"for video={context.video_id}"
    )

    return presets


# ── Private helpers ──────────────────────────────────────────

def _index_titles(
    variants: Optional[ContentVariants],
) -> Dict[Platform, TitleVariant]:
    """Select best title variant per platform (highest confidence)."""
    if not variants or not variants.titles:
        return {}

    best: Dict[Platform, TitleVariant] = {}
    for tv in variants.titles:
        existing = best.get(tv.platform)
        if existing is None or tv.confidence > existing.confidence:
            best[tv.platform] = tv
    return best


def _index_descriptions(
    variants: Optional[ContentVariants],
) -> Dict[Platform, DescriptionVariant]:
    """Select first description variant per platform."""
    if not variants or not variants.descriptions:
        return {}

    best: Dict[Platform, DescriptionVariant] = {}
    for dv in variants.descriptions:
        if dv.platform not in best:
            best[dv.platform] = dv
    return best


def _index_hashtags(
    context: VideoContext,
) -> Dict[Platform, HashtagSet]:
    """Build hashtag lookup from any HashtagSets stored on thumbnail_crops context.

    Note: HashtagSets are not stored directly on VideoContext — they live
    inside UploadPresets. This helper looks for them from the pipeline's
    hashtag_normalizer output, which the pipeline will have stored
    temporarily. For now, return empty — the pipeline (Phase 4) will
    pass hashtag sets in when wiring everything together.
    """
    # V1.2 HashtagSets are produced by hashtag_normalizer and will be
    # plumbed through by the pipeline. At the action layer, we can't
    # access them from VideoContext directly since they're not fields.
    # The pipeline will call build_upload_presets_with_hashtags instead.
    return {}


def build_upload_presets_with_hashtags(
    context: VideoContext,
    hashtag_sets: List[HashtagSet],
    thumbnail_crops: Optional[List[ThumbnailCrop]] = None,
) -> List[UploadPreset]:
    """
    Synchronous variant that accepts hashtag sets and crops directly.

    Called by the pipeline (Phase 4) which has the hashtag sets from
    the normalizer step and crops from the cropper step.
    """
    bundles = context.platform_bundles

    if not bundles:
        return []

    titles_by_platform = _index_titles(context.content_variants)
    descriptions_by_platform = _index_descriptions(context.content_variants)

    # Index hashtags by platform
    hs_by_platform: Dict[Platform, HashtagSet] = {}
    for hs in hashtag_sets:
        if hs.platform not in hs_by_platform:
            hs_by_platform[hs.platform] = hs

    # Index crops by platform (best score per platform)
    crops_by_platform: Dict[Platform, ThumbnailCrop] = {}
    if thumbnail_crops:
        for tc in thumbnail_crops:
            existing = crops_by_platform.get(tc.platform)
            if existing is None or tc.score > existing.score:
                crops_by_platform[tc.platform] = tc

    presets: List[UploadPreset] = []

    for bundle in bundles:
        platform = bundle.platform
        fmt = PLATFORM_FORMATS.get(platform, PLATFORM_FORMATS[Platform.CIRCO])

        preset = UploadPreset(
            platform=platform,
            teaser_id=bundle.teaser_id,
            format="mp4",
            aspect_ratio=fmt["aspect_ratio"],
            max_duration=fmt["max_duration"],
            resolution=fmt["resolution"],
            title=titles_by_platform.get(platform),
            description=descriptions_by_platform.get(platform),
            hashtags=hs_by_platform.get(platform),
            thumbnail=crops_by_platform.get(platform),
            export_path=bundle.output_path if bundle.exported else None,
        )
        presets.append(preset)

    return presets


def _index_crops(
    crops: List[ThumbnailCrop],
) -> Dict[Platform, ThumbnailCrop]:
    """Select best crop per platform (highest score)."""
    if not crops:
        return {}

    best: Dict[Platform, ThumbnailCrop] = {}
    for tc in crops:
        existing = best.get(tc.platform)
        if existing is None or tc.score > existing.score:
            best[tc.platform] = tc
    return best
