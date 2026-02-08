"""
Content Generator — produces title and description variants per platform.

Takes VideoContext signals (transcript, topics, summary, speech regions)
and generates multiple title/description variants for each platform,
grounded in actual content rather than generic templates.

Title variants: 3-5 per platform across different styles (hook, descriptive,
question, listicle, emotional).

Description variants: 2-3 per platform with optional CTA and timestamp
chapter markers derived from speech regions.

Post-generation enforcement: titles truncated to 100 chars, descriptions
truncated to platform-specific limits (same approach as V1.1's
platform_packager title truncation).
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

from src.context.models import (
    ContentVariants,
    DescriptionVariant,
    Platform,
    PLATFORM_DESCRIPTION_LIMITS,
    TitleStyle,
    TitleVariant,
    VideoContext,
)

logger = logging.getLogger(__name__)


# ── Public API ───────────────────────────────────────────────

async def generate_content(
    context: VideoContext,
    ai_service,
    platforms: Optional[List[Platform]] = None,
) -> ContentVariants:
    """
    Generate title and description variants for the given platforms.

    Args:
        context: VideoContext with transcript, topics, summary, speech regions.
        ai_service: AIService (Protocol) with generate_titles/generate_descriptions.
        platforms: Platforms to generate for. Defaults to all platforms.

    Returns:
        ContentVariants with titles and descriptions per platform.
    """
    if platforms is None:
        platforms = list(Platform)

    logger.info(
        f"Generating content variants for {len(platforms)} platforms "
        f"(video={context.video_id})"
    )

    titles = await _generate_titles(context, ai_service, platforms)
    descriptions = await _generate_descriptions(context, ai_service, platforms)

    variants = ContentVariants(
        titles=titles,
        descriptions=descriptions,
        generated_at=datetime.utcnow(),
    )

    logger.info(
        f"Content generation complete: {len(titles)} titles, "
        f"{len(descriptions)} descriptions for video={context.video_id}"
    )

    return variants


# ── Private helpers ──────────────────────────────────────────

async def _generate_titles(
    context: VideoContext,
    ai_service,
    platforms: List[Platform],
) -> List[TitleVariant]:
    """Generate title variants across all platforms and styles."""
    if ai_service is None:
        logger.debug("No AI service provided; skipping title generation")
        return []

    try:
        titles = await ai_service.generate_titles(context, platforms)
        # Post-generation enforcement: truncate to 100 chars
        enforced = []
        for tv in titles:
            if len(tv.text) > 100:
                tv = TitleVariant(
                    text=tv.text[:100],
                    style=tv.style,
                    platform=tv.platform,
                    confidence=tv.confidence,
                )
            enforced.append(tv)
        logger.debug(f"Generated {len(enforced)} title variants")
        return enforced
    except Exception as e:
        logger.warning(f"AI title generation failed: {e}")
        return []


async def _generate_descriptions(
    context: VideoContext,
    ai_service,
    platforms: List[Platform],
) -> List[DescriptionVariant]:
    """Generate description variants across all platforms."""
    if ai_service is None:
        logger.debug("No AI service provided; skipping description generation")
        return []

    try:
        descriptions = await ai_service.generate_descriptions(context, platforms)
        # Post-generation enforcement: truncate to platform limits
        enforced = []
        for dv in descriptions:
            limit = PLATFORM_DESCRIPTION_LIMITS.get(dv.platform, 5000)
            if len(dv.text) > limit:
                dv = DescriptionVariant(
                    text=dv.text[:limit],
                    platform=dv.platform,
                    includes_cta=dv.includes_cta,
                    includes_timestamps=dv.includes_timestamps,
                )
            enforced.append(dv)
        logger.debug(f"Generated {len(enforced)} description variants")
        return enforced
    except Exception as e:
        logger.warning(f"AI description generation failed: {e}")
        return []
