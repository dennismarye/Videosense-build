"""
Summary Generator — produces a 1-2 sentence video description.

Uses the AI service when a transcript is available, with a deterministic
fallback that constructs a description from metadata (duration, scene count,
speech presence, quality level).
"""

import logging
from typing import Optional

from src.context.models import VideoContext

logger = logging.getLogger(__name__)


def _format_duration(seconds: float) -> str:
    """Format duration as a human-readable string (e.g., '2m30s', '45s')."""
    if seconds <= 0:
        return "0s"
    mins = int(seconds // 60)
    secs = int(seconds % 60)
    if mins > 0 and secs > 0:
        return f"{mins}m{secs}s"
    elif mins > 0:
        return f"{mins}m"
    else:
        return f"{secs}s"


def _build_fallback_summary(context: VideoContext) -> str:
    """
    Construct a summary from metadata when no transcript or AI is available.

    Format: "A {duration} video with {scene_count} scenes and {speech info}.
             Quality rated {level} ({score}/100)."
    """
    dur_str = _format_duration(context.duration)
    scene_count = len(context.scenes)
    has_speech = len(context.speech_regions) > 0

    speech_info = "spoken content" if has_speech else "no detected speech"

    parts = [
        f"A {dur_str} video with {scene_count} scene{'s' if scene_count != 1 else ''} "
        f"and {speech_info}."
    ]

    if context.overall_quality:
        quality = context.overall_quality
        parts.append(f"Quality rated {quality.level.value} ({quality.score}/100).")

    return " ".join(parts)


async def generate_summary(
    context: VideoContext,
    transcript: str,
    ai_service,
) -> str:
    """
    Generate a 1-2 sentence video description.

    Algorithm:
      1. If transcript is available and non-empty, call ai_service.generate_summary()
      2. If no transcript or AI fails, construct from metadata (duration, scenes,
         speech presence, quality level)

    Args:
        context: The full VideoContext with populated signals.
        transcript: Combined transcript text (may be empty).
        ai_service: An AIService implementation (real or mock).

    Returns:
        A 1-2 sentence summary string.
    """
    # Try AI-powered summary when transcript is available
    if transcript and transcript.strip():
        try:
            summary = await ai_service.generate_summary(
                video_path=context.source_path or "",
                transcript=transcript,
                duration=context.duration,
                scene_count=len(context.scenes),
            )
            if summary and summary.strip():
                logger.info(
                    f"AI summary generated for {context.video_id}: "
                    f"{len(summary)} chars"
                )
                return summary
            else:
                logger.warning(
                    f"AI returned empty summary for {context.video_id}, "
                    f"falling back to metadata"
                )
        except Exception as e:
            logger.warning(
                f"AI summary generation failed for {context.video_id}, "
                f"falling back to metadata: {e}"
            )

    # Fallback: construct from metadata
    fallback = _build_fallback_summary(context)
    logger.info(
        f"Fallback summary for {context.video_id}: {fallback!r}"
    )
    return fallback
