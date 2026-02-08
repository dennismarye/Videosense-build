"""
Hook Scorer — AI-enhanced analysis of the first 3-5 seconds.

The hook is the single most important factor in viewer retention.
This module extracts early signals (scenes, speech, audio, visual quality)
from the first 5 seconds, computes a deterministic base score, then
blends it with an AI-enhanced score for the final result.

Blend formula: final = 0.4 * base + 0.6 * ai_score
"""

import logging
from typing import List, Optional

from src.context.models import HookScore, ThumbnailCandidate, VideoContext

logger = logging.getLogger(__name__)

# ── Thresholds ───────────────────────────────────────────────

EARLY_SCENE_CUTOFF = 5.0   # seconds — scenes must start before this
EARLY_SPEECH_CUTOFF = 3.0  # seconds — speech must start before this
AUDIO_ENERGY_THRESHOLD = 0.5
THUMBNAIL_QUALITY_THRESHOLD = 0.5

# ── Score weights for deterministic base ─────────────────────

WEIGHT_EARLY_SCENE = 0.3
WEIGHT_EARLY_SPEECH = 0.3
WEIGHT_AUDIO_ENERGY = 0.2
WEIGHT_VISUAL_QUALITY = 0.2

# ── Blending weights ────────────────────────────────────────

BASE_WEIGHT = 0.4
AI_WEIGHT = 0.6


def _extract_early_signals(
    context: VideoContext,
    thumbnail_candidates: List[ThumbnailCandidate],
) -> dict:
    """
    Extract signals from the first 5 seconds of the video.

    Returns a dict with:
      - early_scenes: scenes starting before 5s
      - early_speech: speech regions starting before 3s
      - audio_energy: overall audio energy (0.0-1.0)
      - visual_quality: best thumbnail score in first 5s
    """
    early_scenes = [s for s in context.scenes if s.start < EARLY_SCENE_CUTOFF]
    early_speech = [r for r in context.speech_regions if r.start < EARLY_SPEECH_CUTOFF]

    audio_energy = context.audio_tone.energy if context.audio_tone else 0.0

    # Find the best thumbnail candidate within the first 5 seconds
    early_thumbnails = [
        t for t in thumbnail_candidates
        if t.timestamp < EARLY_SCENE_CUTOFF
    ]
    visual_quality = max(
        (t.score for t in early_thumbnails), default=0.0
    )

    return {
        "early_scenes": early_scenes,
        "early_speech": early_speech,
        "audio_energy": audio_energy,
        "visual_quality": visual_quality,
    }


def _compute_base_score(signals: dict) -> tuple[float, list[str]]:
    """
    Compute a deterministic base score from early signals.

    Same logic as V0: additive scoring from presence of key signals.
    Returns (score, factors) where factors is a list of human-readable strings.
    """
    score = 0.0
    factors: list[str] = []

    if signals["early_scenes"]:
        score += WEIGHT_EARLY_SCENE
        count = len(signals["early_scenes"])
        factors.append(f"{count} scene{'s' if count != 1 else ''} in first {EARLY_SCENE_CUTOFF:.0f}s")

    if signals["early_speech"]:
        score += WEIGHT_EARLY_SPEECH
        factors.append(f"voice onset within {EARLY_SPEECH_CUTOFF:.0f}s")

    if signals["audio_energy"] > AUDIO_ENERGY_THRESHOLD:
        score += WEIGHT_AUDIO_ENERGY
        factors.append(f"strong audio energy ({signals['audio_energy']:.2f})")

    if signals["visual_quality"] > THUMBNAIL_QUALITY_THRESHOLD:
        score += WEIGHT_VISUAL_QUALITY
        factors.append(f"good visual quality ({signals['visual_quality']:.2f})")

    score = min(score, 1.0)
    return score, factors


def _build_fallback_analysis(base_score: float, factors: list[str]) -> str:
    """Build a human-readable analysis string from deterministic signals."""
    if factors:
        return f"Hook score {base_score:.2f}: {', '.join(factors)}."
    return "Weak hook — no strong opening signals detected in the first 5 seconds."


async def score_hook(
    context: VideoContext,
    ai_service,
    thumbnail_candidates: List[ThumbnailCandidate],
) -> HookScore:
    """
    Score the hook (first 3-5 seconds) of a video.

    Algorithm:
      1. Extract early signals (scenes, speech, audio energy, visual quality)
      2. Compute a deterministic base score (additive, max 1.0)
      3. Call ai_service.analyze_hook() for AI-enhanced scoring
      4. Blend: final = 0.4 * base + 0.6 * ai_score
      5. Use AI analysis string, or generate from signals if AI returned None

    Args:
        context: The full VideoContext with populated signals.
        ai_service: An AIService implementation (real or mock).
        thumbnail_candidates: Thumbnail candidates (may include V1 rescored ones).

    Returns:
        HookScore with blended score and analysis string.
    """
    # 1. Extract signals from the first 5 seconds
    signals = _extract_early_signals(context, thumbnail_candidates)

    logger.info(
        f"Hook signals for {context.video_id}: "
        f"early_scenes={len(signals['early_scenes'])}, "
        f"early_speech={len(signals['early_speech'])}, "
        f"audio_energy={signals['audio_energy']:.2f}, "
        f"visual_quality={signals['visual_quality']:.2f}"
    )

    # 2. Compute deterministic base score
    base_score, factors = _compute_base_score(signals)

    # 3. Call AI service for enhanced analysis
    ai_result: Optional[HookScore] = None
    try:
        ai_result = await ai_service.analyze_hook(
            video_path=context.source_path or "",
            duration=context.duration,
            scenes=context.scenes,
            speech_regions=context.speech_regions,
            audio_energy=signals["audio_energy"],
        )
        logger.info(
            f"AI hook analysis for {context.video_id}: "
            f"score={ai_result.score:.3f}, analysis={ai_result.analysis!r}"
        )
    except Exception as e:
        logger.warning(
            f"AI hook analysis failed for {context.video_id}, "
            f"falling back to base score only: {e}"
        )

    # 4. Blend scores
    if ai_result is not None:
        ai_score = ai_result.score
        final_score = BASE_WEIGHT * base_score + AI_WEIGHT * ai_score
    else:
        # No AI result — use base score alone
        final_score = base_score

    final_score = round(min(max(final_score, 0.0), 1.0), 3)

    # 5. Choose analysis string
    if ai_result is not None and ai_result.analysis:
        analysis = ai_result.analysis
    else:
        analysis = _build_fallback_analysis(base_score, factors)

    ai_display = "N/A" if ai_result is None else f"{ai_result.score:.3f}"
    logger.info(
        f"Final hook score for {context.video_id}: {final_score} "
        f"(base={base_score:.3f}, ai={ai_display})"
    )

    return HookScore(score=final_score, analysis=analysis)
