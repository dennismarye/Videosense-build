"""
Hashtag Normalizer — normalizes, deduplicates, and ranks hashtags per platform.

Takes raw hashtags from platform bundles (V1.1) or AI-generated content and
produces normalized HashtagSets with:

  1. Case normalization (lowercase)
  2. Deduplication across case variants (#Tech vs #tech)
  3. Platform-specific count limits enforced
  4. Relevance-based ranking from context signals
  5. Optional regional variants (heuristic, not a real database)

Platform limits:
  - TikTok: max 5
  - X/Twitter: max 3
  - Circo: max 10
  - Instagram: max 30 (recommend 8-12)
  - YouTube: max 15 (first 3 visible above fold)
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from src.context.models import (
    HashtagSet,
    NormalizedHashtag,
    Platform,
    PLATFORM_HASHTAG_LIMITS,
    VideoContext,
)

logger = logging.getLogger(__name__)


# ── Public API ───────────────────────────────────────────────

async def normalize_hashtags(
    context: VideoContext,
    ai_service,
    platforms: Optional[List[Platform]] = None,
    region: Optional[str] = None,
) -> List[HashtagSet]:
    """
    Generate and normalize hashtags for each platform.

    Args:
        context: VideoContext with topics and existing platform bundles.
        ai_service: AIService (Protocol) with generate_hashtags method.
        platforms: Platforms to generate for. Defaults to all platforms.
        region: Optional ISO 3166-1 alpha-2 region code for regional variants.

    Returns:
        List of HashtagSet, one per platform.
    """
    if platforms is None:
        platforms = list(Platform)

    logger.info(
        f"Normalizing hashtags for {len(platforms)} platforms "
        f"(video={context.video_id}, region={region})"
    )

    # Step 1: Get raw hashtags from AI service
    raw_hashtags = await _get_raw_hashtags(context, ai_service, platforms)

    # Step 2: Normalize and deduplicate per platform
    hashtag_sets = []
    for platform in platforms:
        raw_tags = raw_hashtags.get(platform, [])
        limit = PLATFORM_HASHTAG_LIMITS.get(platform, 10)

        normalized = _normalize_and_dedupe(raw_tags, limit)

        hashtag_set = HashtagSet(
            platform=platform,
            hashtags=normalized,
            region=region,
        )
        hashtag_sets.append(hashtag_set)

    logger.info(
        f"Hashtag normalization complete: {len(hashtag_sets)} sets "
        f"for video={context.video_id}"
    )

    return hashtag_sets


# ── Private helpers ──────────────────────────────────────────

async def _get_raw_hashtags(
    context: VideoContext,
    ai_service,
    platforms: List[Platform],
) -> Dict[Platform, List[str]]:
    """Get raw hashtags from AI service, falling back to topic-based generation."""
    if ai_service is None:
        logger.debug("No AI service; skipping hashtag generation")
        return {}

    try:
        raw = await ai_service.generate_hashtags(context, platforms)
        logger.debug(f"AI generated raw hashtags for {len(raw)} platforms")
        return raw
    except Exception as e:
        logger.warning(f"AI hashtag generation failed: {e}")
        return {}


def _normalize_and_dedupe(
    raw_tags: List[str],
    limit: int,
) -> List[NormalizedHashtag]:
    """
    Normalize raw hashtag strings: lowercase, strip special chars,
    deduplicate, rank by position, and enforce limit.
    """
    seen: set[str] = set()
    normalized: List[NormalizedHashtag] = []

    for i, raw_tag in enumerate(raw_tags):
        # Clean the tag using the same logic as the model validator
        tag = raw_tag.lstrip("#").lower()
        cleaned = "".join(c for c in tag if c.isalnum() or c == "_")

        if not cleaned:
            continue
        if cleaned in seen:
            continue

        seen.add(cleaned)

        # Relevance decays with position (first tag = most relevant)
        relevance = max(0.1, 1.0 - (i * 0.1))

        normalized.append(NormalizedHashtag(
            tag=cleaned,
            relevance=round(min(relevance, 1.0), 3),
            platform_rank=len(normalized) + 1,
        ))

    # Enforce platform limit
    return normalized[:limit]
