"""
Moment Detector — segments a video into scored "moments" based on signal convergence.

Takes the populated Context Graph and identifies temporal segments that
represent cohesive moments, scoring them by signal density (speech, scenes,
audio energy, silence ratio, duration fitness).

This is the first stage of clip generation: raw moments are later
refined and ranked by clip_ranker.py.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List

from src.context.models import VideoContext, TimeRange

logger = logging.getLogger(__name__)

# ── Thresholds ────────────────────────────────────────────────
MIN_SEGMENT_DURATION = 3.0    # Merge adjacent segments shorter than this
MAX_SEGMENT_DURATION = 60.0   # Split segments longer than this at silence
MIN_MOMENT_DURATION = 5.0     # Discard moments shorter than this


@dataclass
class Moment:
    """A scored temporal segment of the video."""
    start: float
    end: float
    raw_score: float          # 0.0 - 1.0
    has_speech: bool
    scene_count: int
    audio_energy: float
    signals: dict = field(default_factory=dict)


# ── Public API ────────────────────────────────────────────────

def detect_moments(context: VideoContext) -> List[Moment]:
    """
    Segment a video into scored moments from the Context Graph.

    Pipeline:
      1. Build initial segments from scene boundaries
      2. Merge short adjacent segments (<3s)
      3. Split long segments (>60s) at silence boundaries
      4. Score each moment by signal convergence
      5. Filter out moments <5s
      6. Sort by raw_score descending
    """
    logger.info(f"Detecting moments for video={context.video_id}")

    # Step 1: initial segments from scene boundaries
    segments = _build_scene_segments(context)
    logger.debug(f"Initial segments from scenes: {len(segments)}")

    # Step 2: merge short segments
    segments = _merge_short_segments(segments)
    logger.debug(f"After merging short segments: {len(segments)}")

    # Step 3: split long segments at silence boundaries
    segments = _split_long_segments(segments, context.silence_regions)
    logger.debug(f"After splitting long segments: {len(segments)}")

    # Step 4: score each segment into a Moment
    max_scenes = max(
        (_count_scenes_in_range(s[0], s[1], context.scenes) for s in segments),
        default=1,
    )
    max_scenes = max(max_scenes, 1)  # avoid division by zero

    audio_energy = (
        context.audio_tone.energy if context.audio_tone else 0.0
    )

    moments: List[Moment] = []
    for seg_start, seg_end in segments:
        duration = seg_end - seg_start
        if duration < MIN_MOMENT_DURATION:
            continue

        has_speech = _has_speech_overlap(seg_start, seg_end, context)
        scene_count = _count_scenes_in_range(seg_start, seg_end, context.scenes)
        silence_ratio = _silence_ratio_in_range(
            seg_start, seg_end, context.silence_regions,
        )
        duration_fitness = _duration_fitness(duration)

        raw_score = (
            (1.0 if has_speech else 0.0) * 0.30
            + (scene_count / max_scenes) * 0.20
            + audio_energy * 0.20
            + (1.0 - silence_ratio) * 0.15
            + duration_fitness * 0.15
        )
        raw_score = round(min(max(raw_score, 0.0), 1.0), 4)

        moments.append(Moment(
            start=round(seg_start, 3),
            end=round(seg_end, 3),
            raw_score=raw_score,
            has_speech=has_speech,
            scene_count=scene_count,
            audio_energy=round(audio_energy, 3),
            signals={
                "silence_ratio": round(silence_ratio, 3),
                "duration_fitness": round(duration_fitness, 3),
                "duration": round(duration, 3),
            },
        ))

    # Step 6: sort by raw_score descending
    moments.sort(key=lambda m: m.raw_score, reverse=True)

    logger.info(
        f"Detected {len(moments)} moments for video={context.video_id} "
        f"(top score={moments[0].raw_score if moments else 0})"
    )
    return moments


# ── Segment construction helpers ──────────────────────────────

def _build_scene_segments(context: VideoContext) -> List[tuple]:
    """
    Build (start, end) segments from scene boundaries.

    If no scenes are detected, returns a single segment spanning
    the entire video duration.
    """
    if not context.scenes:
        if context.duration > 0:
            return [(0.0, context.duration)]
        return []

    # Collect unique boundary timestamps and sort them
    boundaries = set()
    for scene in context.scenes:
        boundaries.add(scene.start)
        boundaries.add(scene.end)

    # Ensure 0.0 and video duration are included
    boundaries.add(0.0)
    if context.duration > 0:
        boundaries.add(context.duration)

    sorted_boundaries = sorted(boundaries)

    # Adjacent pairs become segments
    segments = []
    for i in range(len(sorted_boundaries) - 1):
        seg_start = sorted_boundaries[i]
        seg_end = sorted_boundaries[i + 1]
        if seg_end > seg_start:
            segments.append((seg_start, seg_end))

    return segments


def _merge_short_segments(segments: List[tuple]) -> List[tuple]:
    """Merge adjacent segments shorter than MIN_SEGMENT_DURATION."""
    if not segments:
        return []

    merged: List[tuple] = []
    current_start, current_end = segments[0]

    for seg_start, seg_end in segments[1:]:
        current_duration = current_end - current_start
        next_duration = seg_end - seg_start

        # If current segment is short, absorb the next one
        if current_duration < MIN_SEGMENT_DURATION:
            current_end = seg_end
        # If next segment is short, absorb it into current
        elif next_duration < MIN_SEGMENT_DURATION:
            current_end = seg_end
        else:
            merged.append((current_start, current_end))
            current_start, current_end = seg_start, seg_end

    merged.append((current_start, current_end))
    return merged


def _split_long_segments(
    segments: List[tuple],
    silence_regions: List[TimeRange],
) -> List[tuple]:
    """Split segments longer than MAX_SEGMENT_DURATION at silence boundaries."""
    result: List[tuple] = []

    for seg_start, seg_end in segments:
        duration = seg_end - seg_start

        if duration <= MAX_SEGMENT_DURATION:
            result.append((seg_start, seg_end))
            continue

        # Find silence boundaries within this segment
        split_points = []
        for sr in silence_regions:
            midpoint = (sr.start + sr.end) / 2.0
            if seg_start < midpoint < seg_end:
                split_points.append(midpoint)

        if not split_points:
            # No silence boundaries to split at; keep as-is
            result.append((seg_start, seg_end))
            continue

        split_points.sort()
        all_points = [seg_start] + split_points + [seg_end]

        for i in range(len(all_points) - 1):
            sub_start = all_points[i]
            sub_end = all_points[i + 1]
            if sub_end > sub_start:
                result.append((sub_start, sub_end))

    return result


# ── Scoring helpers ───────────────────────────────────────────

def _regions_overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> bool:
    """Check if two time ranges overlap."""
    return a_start < b_end and b_start < a_end


def _has_speech_overlap(start: float, end: float, context: VideoContext) -> bool:
    """Check if any speech region overlaps the given time range."""
    for sr in context.speech_regions:
        if _regions_overlap(start, end, sr.start, sr.end):
            return True
    return False


def _count_scenes_in_range(start: float, end: float, scenes) -> int:
    """Count how many scene boundaries fall within a time range."""
    count = 0
    for scene in scenes:
        # A scene boundary is at scene.start; count if it falls within range
        if start < scene.start < end:
            count += 1
    return count


def _silence_ratio_in_range(
    start: float,
    end: float,
    silence_regions: List[TimeRange],
) -> float:
    """Calculate the proportion of a time range that is silence."""
    duration = end - start
    if duration <= 0:
        return 0.0

    total_silence = 0.0
    for sr in silence_regions:
        overlap_start = max(start, sr.start)
        overlap_end = min(end, sr.end)
        if overlap_end > overlap_start:
            total_silence += overlap_end - overlap_start

    return min(total_silence / duration, 1.0)


def _duration_fitness(duration: float) -> float:
    """
    Score how well the duration fits ideal clip lengths.

    - 15-60s: 1.0 (ideal short-form range)
    - 8-120s: 0.7 (acceptable)
    - Otherwise: 0.4 (too short or too long)
    """
    if 15.0 <= duration <= 60.0:
        return 1.0
    elif 8.0 <= duration <= 120.0:
        return 0.7
    else:
        return 0.4
