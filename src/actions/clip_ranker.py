"""
Clip Ranker — converts scored Moments into ranked SuggestedClips.

Takes raw moments from moment_detector and applies:
  1. Speech-boundary alignment penalties
  2. Format selection (landscape, portrait, square)
  3. Multi-format variant generation for high-scoring moments
  4. Optional AI re-ranking via AIService
  5. Human-readable rationale construction

Produces a final list of top-15 SuggestedClips ready for the API.
"""

from __future__ import annotations

import logging
from typing import List

from src.actions.moment_detector import Moment
from src.context.models import (
    ClipFormat,
    SuggestedClip,
    VideoContext,
)

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────
MIN_SCORE_THRESHOLD = 0.2      # Ignore moments below this
HIGH_SCORE_THRESHOLD = 0.6     # Generate multi-format variants above this
SPEECH_BOUNDARY_PENALTY = 0.1  # Penalty for cutting mid-speech
MAX_CLIPS = 15                 # Maximum clips returned


# ── Public API ────────────────────────────────────────────────

async def rank_clips(
    moments: List[Moment],
    context: VideoContext,
    ai_service,
) -> List[SuggestedClip]:
    """
    Rank moments and produce SuggestedClips.

    Pipeline:
      1. Filter moments by minimum score threshold
      2. Apply speech-boundary alignment penalties
      3. Determine format per moment (landscape / portrait / square)
      4. Generate multi-format variants for high-scoring moments
      5. Optionally re-rank via AI service
      6. Sort by final score, take top 15
      7. Attach human-readable rationale to each clip
    """
    logger.info(
        f"Ranking clips for video={context.video_id} "
        f"from {len(moments)} candidate moments"
    )

    # Step 1: filter by minimum score
    candidates = [m for m in moments if m.raw_score > MIN_SCORE_THRESHOLD]
    logger.debug(f"Candidates after score filter: {len(candidates)}")

    if not candidates:
        logger.info("No moments above score threshold; returning empty clip list")
        return []

    # Steps 2-4: build clip candidates with penalties and format selection
    clips: List[SuggestedClip] = []

    for moment in candidates:
        score = moment.raw_score

        # Step 2: speech-boundary penalty
        score = _apply_speech_boundary_penalty(moment, context, score)

        # Step 3: determine best format
        duration = moment.end - moment.start
        primary_format = _select_format(duration, moment.has_speech)

        # Create primary clip
        primary_clip = SuggestedClip(
            start=moment.start,
            end=moment.end,
            score=round(min(max(score, 0.0), 1.0), 4),
            rationale=_build_rationale(moment),
            format=primary_format,
        )
        clips.append(primary_clip)

        # Step 4: multi-format variants for high-scoring moments
        if moment.raw_score > HIGH_SCORE_THRESHOLD:
            variants = _generate_format_variants(moment, score, primary_format)
            clips.extend(variants)

    logger.debug(f"Total clip candidates (with variants): {len(clips)}")

    # Step 5: optional AI re-ranking
    clips = await _ai_rerank(clips, context, ai_service)

    # Step 6: sort by score descending and take top N
    clips.sort(key=lambda c: c.score, reverse=True)
    clips = clips[:MAX_CLIPS]

    logger.info(
        f"Ranked {len(clips)} clips for video={context.video_id} "
        f"(top score={clips[0].score if clips else 0})"
    )
    return clips


# ── Speech boundary alignment ────────────────────────────────

def _apply_speech_boundary_penalty(
    moment: Moment,
    context: VideoContext,
    score: float,
) -> float:
    """
    Penalize moments whose start or end falls mid-speech-region.

    Cutting mid-sentence sounds jarring, so we apply a -0.1 penalty
    for each boundary (start, end) that falls inside a speech region.
    """
    for sr in context.speech_regions:
        # Check if moment start is mid-speech (not at start of speech region)
        if sr.start < moment.start < sr.end:
            score -= SPEECH_BOUNDARY_PENALTY
            break

    for sr in context.speech_regions:
        # Check if moment end is mid-speech (not at end of speech region)
        if sr.start < moment.end < sr.end:
            score -= SPEECH_BOUNDARY_PENALTY
            break

    return score


# ── Format selection ──────────────────────────────────────────

def _select_format(duration: float, has_speech: bool) -> ClipFormat:
    """
    Determine the best clip format based on duration and signals.

    - Square (1:1): short clips under 30s
    - Portrait (9:16): clips under 60s with speech (short-form social)
    - Landscape (16:9): default for everything else
    """
    if duration < 30.0:
        return ClipFormat.SQUARE
    elif duration < 60.0 and has_speech:
        return ClipFormat.PORTRAIT
    else:
        return ClipFormat.LANDSCAPE


def _generate_format_variants(
    moment: Moment,
    base_score: float,
    primary_format: ClipFormat,
) -> List[SuggestedClip]:
    """
    Generate additional format variants for high-scoring moments.

    High-scoring moments deserve clips in multiple formats so the
    creator can choose the best one for each platform.
    """
    all_formats = [ClipFormat.LANDSCAPE, ClipFormat.PORTRAIT, ClipFormat.SQUARE]
    variant_formats = [f for f in all_formats if f != primary_format]

    variants: List[SuggestedClip] = []
    for fmt in variant_formats:
        # Variants get a slight score reduction since the primary format
        # was already identified as the best fit
        variant_score = round(base_score * 0.9, 4)
        variants.append(SuggestedClip(
            start=moment.start,
            end=moment.end,
            score=min(max(variant_score, 0.0), 1.0),
            rationale=_build_rationale(moment),
            format=fmt,
        ))

    return variants


# ── AI re-ranking ─────────────────────────────────────────────

async def _ai_rerank(
    clips: List[SuggestedClip],
    context: VideoContext,
    ai_service,
) -> List[SuggestedClip]:
    """
    Optionally re-rank clips using the AI service.

    Falls back gracefully to the heuristic ranking if AI is
    unavailable or fails.
    """
    if ai_service is None:
        logger.debug("No AI service provided; skipping AI re-ranking")
        return clips

    try:
        # Serialize moments for the AI service
        moment_dicts = [
            {
                "start": c.start,
                "end": c.end,
                "score": c.score,
                "format": c.format.value,
                "rationale": c.rationale,
            }
            for c in clips
        ]

        ai_clips = await ai_service.rank_clips(
            moments=moment_dicts,
            video_path=context.source_path or "",
            duration=context.duration,
        )

        if ai_clips:
            logger.info(f"AI re-ranked {len(ai_clips)} clips")
            return ai_clips

    except Exception as e:
        logger.warning(f"AI re-ranking failed, using heuristic scores: {e}")

    return clips


# ── Rationale builder ─────────────────────────────────────────

def _build_rationale(moment: Moment) -> str:
    """
    Construct a human-readable rationale string from moment signals.

    Examples:
      "speech + 3 scene transitions + high energy"
      "no speech, 1 scene transition, low energy, 82% silence"
    """
    parts: List[str] = []

    # Speech
    if moment.has_speech:
        parts.append("speech")
    else:
        parts.append("no speech")

    # Scene transitions
    if moment.scene_count == 1:
        parts.append("1 scene transition")
    elif moment.scene_count > 1:
        parts.append(f"{moment.scene_count} scene transitions")

    # Audio energy
    if moment.audio_energy >= 0.7:
        parts.append("high energy")
    elif moment.audio_energy >= 0.4:
        parts.append("moderate energy")
    else:
        parts.append("low energy")

    # Silence ratio (from signals dict)
    silence_ratio = moment.signals.get("silence_ratio", 0.0)
    if silence_ratio > 0.5:
        parts.append(f"{int(silence_ratio * 100)}% silence")

    # Duration fitness (from signals dict)
    duration_fitness = moment.signals.get("duration_fitness", 0.0)
    if duration_fitness >= 1.0:
        parts.append("ideal length")
    elif duration_fitness >= 0.7:
        parts.append("good length")

    # Duration
    duration = moment.signals.get("duration", moment.end - moment.start)
    parts.append(f"{duration:.0f}s")

    return " + ".join(parts)
