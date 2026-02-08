"""
V1 Analysis Pipeline — extends V0 with AI-powered analysis.

Runs the full V0 deterministic pipeline first (metadata, scenes, silence,
audio, thumbnails, quality, pacing/hook), then layers on AI-enhanced steps:
transcript extraction, quality flags, moment detection, clip ranking,
hook scoring, thumbnail re-ranking, summary generation, and topic/entity/
narrative extraction.

V1 steps are fault-tolerant: if any AI step fails, the pipeline logs the
error and continues. V0 data is always preserved. The pipeline only returns
FAILED status if V0 itself fails.
"""

import logging
import time
from typing import Optional

from src.context.models import VideoContext, JobStatus
from src.config.settings import settings
from src.jobs.pipeline import run_v0_pipeline

logger = logging.getLogger(__name__)


async def run_v1_pipeline(
    context: VideoContext,
    ai_service,
    frames_dir: Optional[str] = None,
) -> VideoContext:
    """
    Execute the V1 AI-enhanced analysis pipeline.

    Steps 1-7:  V0 deterministic pipeline (FFmpeg-based)
    Steps 8-15: AI-enhanced analysis (fault-tolerant)

    Args:
        context: VideoContext with source_path populated.
        ai_service: An AIService implementation (real or mock).
        frames_dir: Optional directory for extracted thumbnail frames.

    Returns:
        Populated VideoContext (status is set by JobManager, not here).
    """
    pipeline_start = time.time()
    video_path = context.source_path or ""

    logger.info(f"Starting V1 pipeline for video={context.video_id}")

    # ── Steps 1-7: V0 deterministic pipeline ──────────────────
    context = await run_v0_pipeline(context, frames_dir)

    if context.status == JobStatus.FAILED:
        logger.error(f"V0 pipeline failed for video={context.video_id}, skipping V1 steps")
        return context

    if context.duration <= 0:
        logger.warning(f"Video has no duration for video={context.video_id}, skipping V1 steps")
        return context

    # Track full transcript across steps (used by summary + topic extraction)
    full_transcript = ""

    # ── Step 8: Transcript extraction ─────────────────────────
    logger.info("[8/15] Extracting transcript...")
    step_start = time.time()
    try:
        from src.context.signals.transcript_extractor import (
            extract_transcript,
            extract_transcript_mock,
            WHISPER_AVAILABLE,
        )

        if WHISPER_AVAILABLE:
            result = await extract_transcript(
                video_path,
                context.speech_regions,
                settings.WHISPER_MODEL_SIZE,
                settings.WHISPER_DEVICE,
                settings.WHISPER_COMPUTE_TYPE,
            )
        else:
            logger.info("  faster-whisper not available, using mock transcript")
            result = await extract_transcript_mock(video_path, context.speech_regions)

        context.speech_regions = result.regions
        full_transcript = result.full_text

        word_count = len(full_transcript.split()) if full_transcript else 0
        keyword_count = len(result.keywords)
        logger.info(
            f"  Transcript done: {word_count} words, "
            f"{keyword_count} keywords ({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Transcript extraction failed: {e}", exc_info=True)
    # Always mark progress even on failure so downstream knows it was attempted
    # (pipeline_progress lives on JobState, not VideoContext — log is sufficient)

    # ── Step 9: Quality flag detection ────────────────────────
    logger.info("[9/15] Detecting quality flags...")
    step_start = time.time()
    try:
        from src.context.signals.quality_flag_detector import detect_quality_flags

        context.quality_flags = detect_quality_flags(
            video_path,
            context.duration,
            context.scenes,
            context.audio_tone,
            context.silence_regions,
        )
        logger.info(
            f"  Found {len(context.quality_flags)} quality flags "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Quality flag detection failed: {e}", exc_info=True)

    # ── Step 10: Moment detection ─────────────────────────────
    logger.info("[10/15] Detecting moments...")
    step_start = time.time()
    moments = []
    try:
        from src.actions.moment_detector import detect_moments

        moments = detect_moments(context)
        logger.info(
            f"  Detected {len(moments)} moments "
            f"(top score={moments[0].raw_score if moments else 0}) "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Moment detection failed: {e}", exc_info=True)

    # ── Step 11: Clip ranking ─────────────────────────────────
    logger.info("[11/15] Ranking clips...")
    step_start = time.time()
    try:
        from src.actions.clip_ranker import rank_clips

        context.suggested_clips = await rank_clips(moments, context, ai_service)
        logger.info(
            f"  Ranked {len(context.suggested_clips)} clips "
            f"(top score={context.suggested_clips[0].score if context.suggested_clips else 0}) "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Clip ranking failed: {e}", exc_info=True)

    # ── Step 12: Hook scoring (AI-enhanced) ───────────────────
    logger.info("[12/15] Scoring hook (AI-enhanced)...")
    step_start = time.time()
    try:
        from src.actions.hook_scorer import score_hook

        context.hook_score = await score_hook(
            context, ai_service, context.thumbnail_candidates
        )
        logger.info(
            f"  Hook score: {context.hook_score.score} "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Hook scoring failed: {e}", exc_info=True)

    # ── Step 13: Thumbnail re-ranking ─────────────────────────
    logger.info("[13/15] Re-ranking thumbnails...")
    step_start = time.time()
    try:
        from src.actions.thumbnail_ranker import rank_thumbnails

        context.thumbnail_candidates = await rank_thumbnails(
            context.thumbnail_candidates, ai_service
        )
        logger.info(
            f"  Top {len(context.thumbnail_candidates)} thumbnails "
            f"(best={context.thumbnail_candidates[0].score if context.thumbnail_candidates else 0}) "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Thumbnail re-ranking failed: {e}", exc_info=True)

    # ── Step 14: Summary generation ───────────────────────────
    logger.info("[14/15] Generating summary...")
    step_start = time.time()
    try:
        from src.actions.summary_generator import generate_summary

        context.summary = await generate_summary(context, full_transcript, ai_service)
        logger.info(
            f"  Summary: {len(context.summary)} chars "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Summary generation failed: {e}", exc_info=True)

    # ── Step 15: Topic / entity / narrative extraction ────────
    logger.info("[15/15] Extracting topics, entities, and narrative beats...")
    step_start = time.time()
    try:
        context.topics = await ai_service.extract_topics(
            full_transcript, video_path, context.duration
        )
        context.entities = await ai_service.extract_entities(
            full_transcript, video_path
        )
        context.narrative_beats = await ai_service.detect_narrative_beats(
            video_path, context.scenes, full_transcript, context.duration
        )
        logger.info(
            f"  {len(context.topics)} topics, "
            f"{len(context.entities)} entities, "
            f"{len(context.narrative_beats)} narrative beats "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Topic/entity/narrative extraction failed: {e}", exc_info=True)

    # ── Done ──────────────────────────────────────────────────
    total_time = time.time() - pipeline_start
    logger.info(
        f"V1 pipeline complete for video={context.video_id}: "
        f"{len(context.scenes)} scenes, "
        f"{len(context.speech_regions)} speech regions, "
        f"{len(context.suggested_clips)} clips, "
        f"{len(context.thumbnail_candidates)} thumbnails, "
        f"hook={context.hook_score.score if context.hook_score else 'N/A'}, "
        f"summary={'yes' if context.summary else 'no'}, "
        f"{len(context.topics)} topics, "
        f"{len(context.entities)} entities, "
        f"{len(context.narrative_beats)} narrative beats "
        f"({total_time:.2f}s total)"
    )

    return context


def create_v1_pipeline(ai_service, frames_dir: Optional[str] = None):
    """
    Returns a pipeline function matching JobManager's expected signature.

    Usage:
        pipeline_fn = create_v1_pipeline(ai_service)
        job_manager.set_pipeline(pipeline_fn)
    """
    async def pipeline(context: VideoContext) -> VideoContext:
        return await run_v1_pipeline(context, ai_service, frames_dir)
    return pipeline
