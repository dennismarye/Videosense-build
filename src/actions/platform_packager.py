"""
Platform Packager — creates platform-specific bundles for teasers.

Takes selected teasers from the Teaser Engine and packages them for
each target platform (TikTok, Instagram Reels, X, YouTube Shorts, Circo)
with platform-specific constraints applied:

  1. Tier-based platform gating (FREE = Circo only, PRO+ = all platforms)
  2. Duration capping per platform limits
  3. AI-generated titles and hashtags tailored to each platform
  4. Watermark flagging for free-tier creators
  5. Format (aspect ratio) assignment from platform constraints

Produces PlatformBundle objects with exported=False; actual file export
is handled downstream by teaser_exporter.
"""

from __future__ import annotations

import logging
from typing import Dict, List

from src.context.models import (
    ClipFormat,
    MonetizationTier,
    Platform,
    PlatformBundle,
    PlatformConstraints,
    Teaser,
    VideoContext,
)

logger = logging.getLogger(__name__)

# ── Platform constraints ─────────────────────────────────────

PLATFORM_CONSTRAINTS: Dict[Platform, PlatformConstraints] = {
    Platform.CIRCO: PlatformConstraints(
        platform=Platform.CIRCO,
        max_duration=60.0,
        aspect_ratio=ClipFormat.LANDSCAPE,
        max_title_chars=150,
        max_hashtags=10,
    ),
    Platform.TIKTOK: PlatformConstraints(
        platform=Platform.TIKTOK,
        max_duration=60.0,
        aspect_ratio=ClipFormat.PORTRAIT,
        max_title_chars=150,
        max_hashtags=5,
    ),
    Platform.INSTAGRAM_REELS: PlatformConstraints(
        platform=Platform.INSTAGRAM_REELS,
        max_duration=90.0,
        aspect_ratio=ClipFormat.PORTRAIT,
        max_title_chars=2200,
        max_hashtags=30,
    ),
    Platform.X: PlatformConstraints(
        platform=Platform.X,
        max_duration=140.0,
        aspect_ratio=ClipFormat.LANDSCAPE,
        max_title_chars=280,
        max_hashtags=3,
    ),
    Platform.YOUTUBE_SHORTS: PlatformConstraints(
        platform=Platform.YOUTUBE_SHORTS,
        max_duration=60.0,
        aspect_ratio=ClipFormat.PORTRAIT,
        max_title_chars=100,
        max_hashtags=5,
    ),
}

# ── Tier-based platform access ───────────────────────────────

TIER_PLATFORM_ACCESS: Dict[MonetizationTier, List[Platform]] = {
    MonetizationTier.FREE: [Platform.CIRCO],
    MonetizationTier.PLUS: [Platform.CIRCO],
    MonetizationTier.PRO: [
        Platform.CIRCO,
        Platform.TIKTOK,
        Platform.INSTAGRAM_REELS,
        Platform.X,
        Platform.YOUTUBE_SHORTS,
    ],
    MonetizationTier.ENTERPRISE: [
        Platform.CIRCO,
        Platform.TIKTOK,
        Platform.INSTAGRAM_REELS,
        Platform.X,
        Platform.YOUTUBE_SHORTS,
    ],
}


# ── Public API ───────────────────────────────────────────────

async def package_for_platforms(
    teasers: List[Teaser],
    context: VideoContext,
    ai_service,
    tier: MonetizationTier = MonetizationTier.FREE,
) -> List[PlatformBundle]:
    """
    Package teasers into platform-specific bundles.

    Pipeline:
      1. Determine allowed platforms from monetization tier
      2. Gather platform constraints for title/hashtag generation
      3. Generate AI titles and hashtags per platform
      4. Build a PlatformBundle for each (teaser, platform) pair
      5. Return all bundles with exported=False (export is a later step)
    """
    logger.info(
        f"Packaging {len(teasers)} teasers for tier={tier.value} "
        f"(video={context.video_id})"
    )

    if not teasers:
        logger.info("No teasers to package; returning empty bundle list")
        return []

    # Step 1: determine allowed platforms and watermark status
    allowed_platforms = _get_allowed_platforms(tier)
    watermark = _should_watermark(tier)

    logger.debug(
        f"Allowed platforms: {[p.value for p in allowed_platforms]}, "
        f"watermark={watermark}"
    )

    # Step 2: build constraint lookups for AI generation
    platform_names = [p.value for p in allowed_platforms]
    max_chars_dict = {
        p.value: PLATFORM_CONSTRAINTS[p].max_title_chars
        for p in allowed_platforms
    }
    max_hashtags_dict = {
        p.value: PLATFORM_CONSTRAINTS[p].max_hashtags
        for p in allowed_platforms
    }

    # Step 3: generate titles and hashtags via AI service
    titles = await _generate_titles(
        ai_service, context, platform_names, max_chars_dict
    )
    hashtags = await _generate_hashtags(
        ai_service, context, platform_names, max_hashtags_dict
    )

    # Step 4: build bundles for each (teaser, platform) pair
    bundles: List[PlatformBundle] = []

    for teaser in teasers:
        for platform in allowed_platforms:
            constraints = PLATFORM_CONSTRAINTS[platform]
            raw_duration = teaser.end - teaser.start
            effective_duration = min(raw_duration, constraints.max_duration)

            bundle = PlatformBundle(
                teaser_id=teaser.teaser_id,
                platform=platform,
                title=titles.get(platform.value, ""),
                hashtags=hashtags.get(platform.value, []),
                format=constraints.aspect_ratio,
                duration=round(effective_duration, 3),
                exported=False,
                watermarked=watermark,
            )
            bundles.append(bundle)

    logger.info(
        f"Created {len(bundles)} platform bundles "
        f"({len(teasers)} teasers x {len(allowed_platforms)} platforms) "
        f"for video={context.video_id}"
    )
    return bundles


# ── Private helpers ──────────────────────────────────────────

def _should_watermark(tier: MonetizationTier) -> bool:
    """Return True if the tier requires a watermark on exported teasers."""
    return tier == MonetizationTier.FREE


def _get_allowed_platforms(tier: MonetizationTier) -> List[Platform]:
    """Return the list of platforms a creator can export to for their tier."""
    return TIER_PLATFORM_ACCESS.get(tier, [Platform.CIRCO])


async def _generate_titles(
    ai_service,
    context: VideoContext,
    platform_names: List[str],
    max_chars_dict: Dict[str, int],
) -> Dict[str, str]:
    """
    Generate platform-tailored titles via the AI service.

    Falls back to an empty dict if AI is unavailable so that bundles
    are still created (titles can be filled in later).
    """
    if ai_service is None:
        logger.debug("No AI service provided; skipping title generation")
        return {}

    try:
        titles = await ai_service.generate_teaser_titles(
            context.summary,
            context.topics,
            platform_names,
            max_chars_dict,
        )
        # Enforce platform title length limits
        for platform_name, title in titles.items():
            max_chars = max_chars_dict.get(platform_name)
            if max_chars and len(title) > max_chars:
                titles[platform_name] = title[:max_chars]
        logger.debug(f"AI generated titles for {len(titles)} platforms")
        return titles
    except Exception as e:
        logger.warning(f"AI title generation failed, using empty titles: {e}")
        return {}


async def _generate_hashtags(
    ai_service,
    context: VideoContext,
    platform_names: List[str],
    max_hashtags_dict: Dict[str, int],
) -> Dict[str, List[str]]:
    """
    Generate platform-tailored hashtags via the AI service.

    Falls back to an empty dict if AI is unavailable so that bundles
    are still created (hashtags can be added later).
    """
    if ai_service is None:
        logger.debug("No AI service provided; skipping hashtag generation")
        return {}

    try:
        hashtags = await ai_service.generate_teaser_hashtags(
            context.topics,
            platform_names,
            max_hashtags_dict,
        )
        # Enforce platform hashtag count limits
        for platform_name, tags in hashtags.items():
            max_tags = max_hashtags_dict.get(platform_name)
            if max_tags and len(tags) > max_tags:
                hashtags[platform_name] = tags[:max_tags]
        logger.debug(f"AI generated hashtags for {len(hashtags)} platforms")
        return hashtags
    except Exception as e:
        logger.warning(
            f"AI hashtag generation failed, using empty hashtags: {e}"
        )
        return {}
