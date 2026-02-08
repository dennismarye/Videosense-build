"""
Teaser Selector — picks 1-3 best teasers from V1's suggested_clips.

Re-scores SuggestedClips for teaser appeal using narrative beat alignment,
speech presence, and duration fitness. Supports three selection modes:

  - STANDARD: top-N by teaser appeal score
  - TRAILER: arc-based selection (one clip per narrative third)
  - HIGHLIGHT_REEL: same as standard (top-N)

Input:  VideoContext with populated suggested_clips and narrative_beats
Output: List[Teaser] (1-3 items) ready for platform packaging
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from src.context.models import (
    NarrativeBeat,
    SeriesContext,
    SuggestedClip,
    Teaser,
    TeaserMode,
    VideoContext,
)

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────

BEAT_PROXIMITY_THRESHOLD = 5.0  # seconds — clip must be within this of a beat
IDEAL_MIN_DURATION = 15.0       # seconds — lower bound for ideal teaser length
IDEAL_MAX_DURATION = 30.0       # seconds — upper bound for ideal teaser length
HARD_MIN_DURATION = 5.0         # seconds — clips shorter than this are excluded
HARD_MAX_DURATION = 90.0        # seconds — clips longer than this are excluded
MAX_INPUT_CLIPS = 15            # maximum clips to consider from suggested_clips


# ── Public API ───────────────────────────────────────────────

async def select_teasers(
    context: VideoContext,
    ai_service,
    max_teasers: int = 3,
    series_context: Optional[SeriesContext] = None,
) -> List[Teaser]:
    """
    Select 1-3 teaser clips from the video's suggested_clips.

    Algorithm:
      1. Take up to 15 suggested_clips (already ranked by moment quality)
      2. Score each clip for teaser appeal (narrative alignment, speech, duration)
      3. Select clips based on teaser mode (standard, trailer, or highlight_reel)
      4. Deduplicate overlapping clips
      5. Return top max_teasers as Teaser objects

    Args:
        context: VideoContext with populated suggested_clips and signals.
        ai_service: AIService instance (reserved for future AI re-ranking).
        max_teasers: Maximum number of teasers to return (default 3).
        series_context: Optional series metadata that controls teaser mode.

    Returns:
        List of Teaser objects, sorted by teaser_score descending.
    """
    clips = context.suggested_clips[:MAX_INPUT_CLIPS]

    # Hard duration filter: exclude clips outside [HARD_MIN, HARD_MAX]
    clips = [
        c for c in clips
        if HARD_MIN_DURATION <= (c.end - c.start) <= HARD_MAX_DURATION
    ]

    if not clips:
        logger.info(f"No suggested clips for video={context.video_id}; returning empty teaser list")
        return []

    logger.info(
        f"Selecting teasers for video={context.video_id} "
        f"from {len(clips)} candidate clips "
        f"(max_teasers={max_teasers})"
    )

    # Step 1: compute teaser appeal for each clip
    clips_with_scores: List[Tuple[SuggestedClip, float, Optional[str]]] = []

    for clip in clips:
        appeal = _compute_teaser_appeal(
            clip, context.narrative_beats, context.speech_regions
        )
        alignment = _find_narrative_alignment(clip, context.narrative_beats)
        clips_with_scores.append((clip, appeal, alignment))

    logger.debug(
        f"Teaser appeal scores: "
        f"{[(c.clip_id[:8], round(s, 3)) for c, s, _ in clips_with_scores]}"
    )

    # Step 2: determine teaser mode
    mode = TeaserMode.STANDARD
    if series_context is not None:
        mode = series_context.teaser_mode
        logger.info(
            f"Series context provided: series={series_context.series_id}, "
            f"episode={series_context.episode_number}, mode={mode.value}"
        )

    # Step 3: select clips based on mode
    if mode == TeaserMode.TRAILER:
        selected = _select_trailer_teasers(
            clips_with_scores, context.duration, max_teasers
        )
    else:
        # STANDARD and HIGHLIGHT_REEL both use top-N selection
        selected = _select_standard_teasers(clips_with_scores, max_teasers)

    # Step 4: convert to Teaser objects
    teasers = [
        Teaser(
            source_clip_id=clip.clip_id,
            start=clip.start,
            end=clip.end,
            teaser_score=round(score, 4),
            mode=mode,
            rationale=clip.rationale,
            narrative_alignment=alignment,
        )
        for clip, score, alignment in selected
    ]

    # Step 5: deduplicate overlapping teasers
    teasers = _deduplicate_overlapping(teasers)

    # Trim to max count after deduplication
    teasers = teasers[:max_teasers]

    logger.info(
        f"Selected {len(teasers)} teasers for video={context.video_id} "
        f"(mode={mode.value}, "
        f"top_score={teasers[0].teaser_score if teasers else 0})"
    )

    return teasers


# ── Teaser appeal scoring ────────────────────────────────────

def _compute_teaser_appeal(
    clip: SuggestedClip,
    narrative_beats: List[NarrativeBeat],
    speech_regions: list,
) -> float:
    """
    Compute a teaser appeal score for a single clip.

    Scoring formula:
      - Base: clip.score * 0.5 (50% from original moment ranking)
      - +0.25 if clip overlaps an "intro" beat (good hook)
      - +0.20 if clip overlaps a "climax" or "development" beat
      - +0.15 if clip contains speech
      - +0.10 if clip duration is in the ideal 15-30s range
      - Capped at 1.0
    """
    score = clip.score * 0.5

    # Narrative beat bonuses
    for beat in narrative_beats:
        if _clip_overlaps_beat(clip, beat):
            if beat.type == "intro":
                score += 0.25
                break  # Only apply one narrative bonus
            elif beat.type in ("climax", "development"):
                score += 0.20
                break

    # Speech bonus
    if _has_speech_overlap(clip, speech_regions):
        score += 0.15

    # Duration fitness bonus
    duration = clip.end - clip.start
    if IDEAL_MIN_DURATION <= duration <= IDEAL_MAX_DURATION:
        score += 0.10

    return min(score, 1.0)


def _clip_overlaps_beat(clip: SuggestedClip, beat: NarrativeBeat) -> bool:
    """Check if a clip's time range is within proximity of a beat's timestamp."""
    return clip.start - BEAT_PROXIMITY_THRESHOLD <= beat.timestamp <= clip.end + BEAT_PROXIMITY_THRESHOLD


# ── Narrative alignment ──────────────────────────────────────

def _find_narrative_alignment(
    clip: SuggestedClip,
    beats: List[NarrativeBeat],
) -> Optional[str]:
    """
    Return the beat type if a clip is within 5s of a beat's timestamp.

    Checks all beats and returns the first match. Returns None if no
    beat is close enough to the clip's time range.
    """
    for beat in beats:
        if _clip_overlaps_beat(clip, beat):
            return beat.type
    return None


# ── Speech overlap detection ─────────────────────────────────

def _has_speech_overlap(clip: SuggestedClip, speech_regions: list) -> bool:
    """
    Check whether a clip overlaps any speech region.

    Returns True if the clip's time range intersects with at least one
    speech region (standard interval overlap test).
    """
    for sr in speech_regions:
        if clip.start < sr.end and clip.end > sr.start:
            return True
    return False


# ── Deduplication ────────────────────────────────────────────

def _deduplicate_overlapping(teasers: List[Teaser]) -> List[Teaser]:
    """
    Remove overlapping teasers, keeping the higher-scored one.

    Two teasers overlap if their shared time exceeds 50% of the
    shorter teaser's duration. The list is assumed to be sorted by
    teaser_score descending (higher-scored teasers are kept).
    """
    # Sort by score descending so we prefer higher-scored teasers
    sorted_teasers = sorted(teasers, key=lambda t: t.teaser_score, reverse=True)
    kept: List[Teaser] = []

    for candidate in sorted_teasers:
        if not any(_overlaps_significantly(candidate, existing) for existing in kept):
            kept.append(candidate)

    return kept


def _overlaps_significantly(a: Teaser, b: Teaser) -> bool:
    """
    Check if two teasers overlap by more than 50% of the shorter one's duration.
    """
    overlap_start = max(a.start, b.start)
    overlap_end = min(a.end, b.end)
    overlap_duration = max(0.0, overlap_end - overlap_start)

    shorter_duration = min(a.end - a.start, b.end - b.start)
    if shorter_duration <= 0:
        return False

    return overlap_duration > (shorter_duration * 0.5)


# ── Selection strategies ─────────────────────────────────────

def _select_trailer_teasers(
    clips_with_scores: List[Tuple[SuggestedClip, float, Optional[str]]],
    duration: float,
    max_count: int,
) -> List[Tuple[SuggestedClip, float, Optional[str]]]:
    """
    Arc-based selection for TRAILER mode.

    Divides the video into thirds (by duration) and picks the
    highest teaser-appeal clip from each third. This ensures the
    trailer covers the full narrative arc.

    If a third has no clips, it is skipped.
    """
    if duration <= 0:
        logger.warning("Video duration is 0; falling back to standard selection")
        return _select_standard_teasers(clips_with_scores, max_count)

    third = duration / 3.0
    boundaries = [
        (0.0, third),
        (third, third * 2),
        (third * 2, duration),
    ]

    selected: List[Tuple[SuggestedClip, float, Optional[str]]] = []

    for start_bound, end_bound in boundaries:
        # Find clips whose midpoint falls within this third
        in_third = [
            (clip, score, alignment)
            for clip, score, alignment in clips_with_scores
            if start_bound <= (clip.start + clip.end) / 2.0 < end_bound
        ]

        if in_third:
            best = max(in_third, key=lambda x: x[1])
            selected.append(best)

        if len(selected) >= max_count:
            break

    if not selected:
        logger.warning("No clips found in any third; falling back to standard selection")
        return _select_standard_teasers(clips_with_scores, max_count)

    # Sort by score descending
    selected.sort(key=lambda x: x[1], reverse=True)

    logger.debug(
        f"Trailer selection: {len(selected)} clips across "
        f"{len(boundaries)} thirds (duration={duration:.1f}s)"
    )

    return selected


def _select_standard_teasers(
    clips_with_scores: List[Tuple[SuggestedClip, float, Optional[str]]],
    max_count: int,
) -> List[Tuple[SuggestedClip, float, Optional[str]]]:
    """
    Standard top-N selection by teaser appeal score.

    Simply sorts by score descending and returns the top max_count clips.
    Used for both STANDARD and HIGHLIGHT_REEL modes.
    """
    sorted_clips = sorted(clips_with_scores, key=lambda x: x[1], reverse=True)
    return sorted_clips[:max_count]
