"""
Thumbnail Ranker — combines V0 extraction with V1 OpenCV + AI scoring.

Action layer module that takes V0 thumbnail candidates and produces a
final ranked list by layering two refinement passes:

  1. OpenCV re-scoring (face detection, contrast, sharpness, composition)
  2. AI re-ranking (optional, via AIService.score_thumbnails)

Blending formula when both passes succeed:
    final_score = 0.7 * opencv_score + 0.3 * ai_score

Graceful fallback chain:
  - OpenCV unavailable  -> use V0 scores, attempt AI-only scoring
  - AI service fails    -> use whatever scores are available
  - Both fail           -> return V0 candidates unchanged
"""

import logging
from typing import List, Optional

from src.context.models import ThumbnailCandidate

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────

# Blending weights when both OpenCV and AI scores are available
OPENCV_WEIGHT = 0.7
AI_WEIGHT = 0.3

# Maximum thumbnails to return
MAX_RANKED_THUMBNAILS = 5


async def rank_thumbnails(
    candidates: List[ThumbnailCandidate],
    ai_service: Optional[object] = None,
) -> List[ThumbnailCandidate]:
    """
    Rank thumbnail candidates using OpenCV re-scoring and optional AI analysis.

    Args:
        candidates: V0 thumbnail candidates with initial scores and frame paths.
        ai_service: Optional AI service implementing score_thumbnails().
                    Pass None to skip AI scoring entirely.

    Returns:
        Top 5 candidates sorted by final score descending.
    """
    if not candidates:
        logger.info("No thumbnail candidates to rank")
        return candidates

    logger.info(f"Ranking {len(candidates)} thumbnail candidates")

    # ── Pass 1: OpenCV re-scoring ────────────────────────────
    opencv_succeeded = False
    try:
        from src.context.signals.thumbnail_scorer import rescore_thumbnails

        rescored = rescore_thumbnails(candidates)
        opencv_succeeded = True
        logger.info(
            f"OpenCV re-scoring complete: {len(rescored)} candidates "
            f"(best={rescored[0].score if rescored else 0})"
        )
    except ImportError:
        logger.warning(
            "thumbnail_scorer import failed (OpenCV not installed) — "
            "using V0 scores for OpenCV pass"
        )
        rescored = list(candidates)
    except Exception as e:
        logger.error(f"OpenCV re-scoring failed: {e}", exc_info=True)
        rescored = list(candidates)

    # ── Pass 2: AI re-ranking (optional) ─────────────────────
    if ai_service is not None:
        try:
            rescored = await _apply_ai_scoring(
                rescored, ai_service, opencv_succeeded
            )
        except Exception as e:
            logger.error(f"AI thumbnail scoring failed: {e}", exc_info=True)
            # Fall through with whatever scores we have

    # ── Final sort + limit ───────────────────────────────────
    rescored.sort(key=lambda c: c.score, reverse=True)
    ranked = rescored[:MAX_RANKED_THUMBNAILS]

    logger.info(
        f"Thumbnail ranking complete: returning top {len(ranked)} "
        f"(scores: {[round(c.score, 3) for c in ranked]})"
    )

    return ranked


async def _apply_ai_scoring(
    candidates: List[ThumbnailCandidate],
    ai_service: object,
    opencv_succeeded: bool,
) -> List[ThumbnailCandidate]:
    """
    Call the AI service to score thumbnails and blend with existing scores.

    When OpenCV succeeded, blends: 0.7 * opencv_score + 0.3 * ai_score.
    When OpenCV was skipped, uses AI scores directly (replaces V0 scores).

    Args:
        candidates: Candidates with current scores (V0 or OpenCV-blended).
        ai_service: AI service with score_thumbnails() method.
        opencv_succeeded: Whether OpenCV pass ran successfully.

    Returns:
        Candidates with AI-blended scores.
    """
    # Convert candidates to dicts for the AI service interface
    candidate_dicts = [
        {
            "timestamp": c.timestamp,
            "score": c.score,
            "reasons": list(c.reasons),
            "frame_path": c.frame_path,
        }
        for c in candidates
    ]

    # AI service needs a video_path — use frame_path dirname as proxy,
    # or empty string if no frames available
    video_path = ""
    for c in candidates:
        if c.frame_path:
            import os
            video_path = os.path.dirname(c.frame_path)
            break

    logger.info(f"Requesting AI scoring for {len(candidate_dicts)} candidates")
    ai_results = await ai_service.score_thumbnails(candidate_dicts, video_path)

    if not ai_results:
        logger.warning("AI service returned no results — keeping current scores")
        return candidates

    # Build a lookup from timestamp -> AI score for merging
    ai_score_map = {}
    for result in ai_results:
        ai_score_map[result.timestamp] = result.score

    # Merge AI scores into existing candidates
    for candidate in candidates:
        ai_score = ai_score_map.get(candidate.timestamp)
        if ai_score is None:
            continue

        if opencv_succeeded:
            # Blend: OpenCV-weighted score + AI score
            blended = OPENCV_WEIGHT * candidate.score + AI_WEIGHT * ai_score
        else:
            # No OpenCV — AI score replaces V0 score directly
            blended = ai_score

        candidate.score = round(min(max(blended, 0.0), 1.0), 3)

        if "ai_scored" not in candidate.reasons:
            candidate.reasons.append("ai_scored")

    logger.info(
        f"AI scoring merged (opencv={'blended' if opencv_succeeded else 'skipped'}, "
        f"matched={len(ai_score_map)}/{len(candidates)} candidates)"
    )

    return candidates
