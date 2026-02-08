"""
V0 Analysis Pipeline — chains deterministic signal extractors.

This is the pipeline function injected into JobManager.
It takes a VideoContext, runs all FFmpeg-based signal extractors,
populates the context graph, and returns it.

V0 scope: metadata, scenes, silence/speech, audio tone, thumbnails, quality.
No AI — everything is FFmpeg-based and deterministic.
"""

import logging
import os
import tempfile
import time
from typing import Optional

from src.context.models import (
    VideoContext,
    PacingScore,
    HookScore,
)
from src.context.signals.metadata_extractor import (
    extract_metadata,
    build_quality_from_metadata,
)
from src.context.signals.scene_detector import detect_scenes
from src.context.signals.silence_detector import (
    detect_speech_regions,
    calculate_silence_ratio,
)
from src.context.signals.audio_analyzer import analyze_audio, has_audio_stream
from src.context.signals.frame_extractor import extract_thumbnail_candidates

logger = logging.getLogger(__name__)

# Directory for extracted thumbnail frames
DEFAULT_FRAMES_DIR = os.path.join(tempfile.gettempdir(), "circo_frames")


async def run_v0_pipeline(
    context: VideoContext,
    frames_dir: Optional[str] = None,
) -> VideoContext:
    """
    Execute the V0 deterministic analysis pipeline.

    Steps (in order):
    1. Metadata extraction (ffprobe)
    2. Scene detection (ffmpeg scene filter)
    3. Silence + speech detection (ffmpeg silencedetect)
    4. Audio analysis (ffmpeg volumedetect)
    5. Thumbnail candidate extraction (ffmpeg frame capture)
    6. Quality assessment (metadata-based scoring)
    7. Pacing + hook scoring (derived from scenes/silence)

    All steps are FFmpeg-only — no AI, fully deterministic.
    """
    video_path = context.source_path
    if not video_path or not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return context

    pipeline_start = time.time()
    frames_output = frames_dir or os.path.join(
        DEFAULT_FRAMES_DIR, context.video_id
    )

    logger.info(f"Starting V0 pipeline for video={context.video_id}")

    # ── Step 1: Metadata ───────────────────────────────────────
    logger.info("[1/7] Extracting metadata...")
    step_start = time.time()
    metadata = extract_metadata(video_path)
    context.duration = metadata["duration"]
    context.file_size = metadata["file_size"]
    logger.info(f"  Metadata done ({time.time() - step_start:.2f}s)")

    if context.duration <= 0:
        logger.warning("Video has no duration — skipping remaining pipeline")
        context.overall_quality = build_quality_from_metadata(metadata)
        return context

    # ── Step 2: Scene detection ────────────────────────────────
    logger.info("[2/7] Detecting scenes...")
    step_start = time.time()
    context.scenes = detect_scenes(video_path)
    logger.info(
        f"  Found {len(context.scenes)} scenes ({time.time() - step_start:.2f}s)"
    )

    # ── Step 3: Silence + speech detection ─────────────────────
    logger.info("[3/7] Detecting silence/speech regions...")
    step_start = time.time()
    has_audio = has_audio_stream(video_path)

    if has_audio:
        silence_regions, speech_regions = detect_speech_regions(
            video_path, context.duration
        )
        context.silence_regions = silence_regions
        context.speech_regions = speech_regions
        silence_ratio = calculate_silence_ratio(silence_regions, context.duration)
    else:
        silence_ratio = 1.0

    logger.info(
        f"  {len(context.silence_regions)} silence, "
        f"{len(context.speech_regions)} speech regions, "
        f"silence ratio={silence_ratio:.2f} "
        f"({time.time() - step_start:.2f}s)"
    )

    # ── Step 4: Audio analysis ─────────────────────────────────
    logger.info("[4/7] Analyzing audio...")
    step_start = time.time()
    if has_audio:
        context.audio_tone = analyze_audio(video_path)
    logger.info(f"  Audio done ({time.time() - step_start:.2f}s)")

    # ── Step 5: Thumbnail candidates ───────────────────────────
    logger.info("[5/7] Extracting thumbnail candidates...")
    step_start = time.time()
    scene_timestamps = [s.start for s in context.scenes if s.start > 0]
    context.thumbnail_candidates = extract_thumbnail_candidates(
        video_path=video_path,
        output_dir=frames_output,
        duration=context.duration,
        scene_timestamps=scene_timestamps,
    )
    logger.info(
        f"  {len(context.thumbnail_candidates)} thumbnails "
        f"({time.time() - step_start:.2f}s)"
    )

    # ── Step 6: Quality assessment ─────────────────────────────
    logger.info("[6/7] Assessing quality...")
    step_start = time.time()
    context.overall_quality = build_quality_from_metadata(metadata)
    logger.info(
        f"  Quality: {context.overall_quality.score}/100 "
        f"({context.overall_quality.level.value}) "
        f"({time.time() - step_start:.2f}s)"
    )

    # ── Step 7: Derived scores ─────────────────────────────────
    logger.info("[7/7] Computing derived scores...")
    step_start = time.time()

    # Pacing score: scenes per minute
    if context.duration > 0 and len(context.scenes) > 0:
        spm = len(context.scenes) / (context.duration / 60.0)
        # Ideal pacing is 3-8 scenes/minute for short-form
        if 3 <= spm <= 8:
            pacing_score = 1.0
        elif 1 <= spm <= 15:
            pacing_score = 0.7
        else:
            pacing_score = 0.4
        context.pacing_score = PacingScore(
            score=round(pacing_score, 3),
            scenes_per_minute=round(spm, 2),
        )

    # Hook score: based on first 5 seconds
    # V0 heuristic: is there a scene change in first 5s? Is audio active?
    early_scenes = [s for s in context.scenes if s.start <= 5.0]
    early_speech = [r for r in context.speech_regions if r.start <= 5.0]
    hook_factors = 0
    if early_scenes:
        hook_factors += 1  # Scene change = visual hook
    if early_speech:
        hook_factors += 1  # Voice in first 5s = engagement
    if context.audio_tone and context.audio_tone.energy > 0.5:
        hook_factors += 1  # High energy opening

    hook_score_val = min(hook_factors / 3.0, 1.0)
    context.hook_score = HookScore(
        score=round(hook_score_val, 3),
    )

    logger.info(
        f"  Pacing: {context.pacing_score.scenes_per_minute if context.pacing_score else 0} spm, "
        f"Hook: {context.hook_score.score} "
        f"({time.time() - step_start:.2f}s)"
    )

    # ── Done ───────────────────────────────────────────────────
    total_time = time.time() - pipeline_start
    logger.info(
        f"V0 pipeline complete for video={context.video_id}: "
        f"{len(context.scenes)} scenes, "
        f"{len(context.speech_regions)} speech regions, "
        f"{len(context.thumbnail_candidates)} thumbnails, "
        f"quality={context.overall_quality.score}/100 "
        f"({total_time:.2f}s total)"
    )

    return context
