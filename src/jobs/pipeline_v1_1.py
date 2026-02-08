"""
V1.1 Teaser Pipeline — extends V1 with teaser generation.

Runs the full V1 pipeline first (V0 deterministic + AI-enhanced, steps 1-15),
then layers on teaser-specific steps: teaser selection, platform packaging,
and teaser export.

V1.1 steps are fault-tolerant: if any teaser step fails, the pipeline logs
the error and continues. V1 data is always preserved. The pipeline only
returns FAILED status if V1 itself fails.
"""

import logging
import time
from typing import Optional

from src.context.models import VideoContext, JobStatus, SeriesContext, TeaserMode, MonetizationTier
from src.config.settings import settings
from src.jobs.pipeline_v1 import run_v1_pipeline

logger = logging.getLogger(__name__)


def _parse_series_context(context: VideoContext) -> Optional[SeriesContext]:
    """Extract series context from VideoContext or return None."""
    if context.series_context:
        return context.series_context
    return None


async def run_v1_1_pipeline(
    context: VideoContext,
    ai_service,
    frames_dir: Optional[str] = None,
) -> VideoContext:
    """
    Execute the V1.1 teaser pipeline.

    Steps 1-15:  V1 pipeline (V0 deterministic + AI-enhanced)
    Steps 16-18: Teaser engine (fault-tolerant)

    Args:
        context: VideoContext with source_path populated.
        ai_service: An AIService implementation (real or mock).
        frames_dir: Optional directory for extracted thumbnail frames.

    Returns:
        Populated VideoContext (status is set by JobManager, not here).
    """
    pipeline_start = time.time()

    logger.info(f"Starting V1.1 pipeline for video={context.video_id}")

    # ── Steps 1-15: V1 pipeline (V0 + AI-enhanced) ────────────
    context = await run_v1_pipeline(context, ai_service, frames_dir)

    if context.status == JobStatus.FAILED:
        logger.error(f"V1 pipeline failed for video={context.video_id}, skipping teaser steps")
        return context

    if not context.suggested_clips:
        logger.info(f"No suggested clips for video={context.video_id}, skipping teaser steps")
        return context

    if not settings.ENABLE_TEASER_ENGINE:
        logger.info(f"Teaser engine disabled, skipping teaser steps for video={context.video_id}")
        return context

    series_context = _parse_series_context(context)

    # ── Step 16: Teaser selection ──────────────────────────────
    logger.info("[16/18] Selecting teasers...")
    step_start = time.time()
    try:
        from src.actions.teaser_selector import select_teasers

        context.teasers = await select_teasers(
            context, ai_service,
            max_teasers=settings.TEASER_MAX_COUNT,
            series_context=series_context,
        )
        if series_context:
            context.series_context = series_context

        logger.info(
            f"  Selected {len(context.teasers)} teasers "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Teaser selection failed: {e}", exc_info=True)

    # ── Step 17: Platform packaging ────────────────────────────
    logger.info("[17/18] Packaging for platforms...")
    step_start = time.time()
    try:
        from src.actions.platform_packager import package_for_platforms

        context.platform_bundles = await package_for_platforms(
            context.teasers, context, ai_service, tier=context.tier,
        )
        logger.info(
            f"  Packaged {len(context.platform_bundles)} platform bundles "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Platform packaging failed: {e}", exc_info=True)

    # ── Step 18: Teaser export ─────────────────────────────────
    logger.info("[18/18] Exporting teasers...")
    step_start = time.time()
    try:
        from src.actions.teaser_exporter import export_teasers

        context.platform_bundles = await export_teasers(
            context.platform_bundles,
            context.teasers,
            context.source_path or "",
            settings.TEASER_EXPORT_DIR,
            watermark_path=settings.TEASER_WATERMARK_PATH or None,
        )
        exported_count = sum(
            1 for b in context.platform_bundles if b.exported
        ) if context.platform_bundles else 0
        logger.info(
            f"  Exported {exported_count} bundles "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Teaser export failed: {e}", exc_info=True)

    # ── Done ──────────────────────────────────────────────────
    total_time = time.time() - pipeline_start
    teaser_count = len(context.teasers)
    bundle_count = len(context.platform_bundles)
    exported_count = sum(
        1 for b in context.platform_bundles if b.exported
    ) if context.platform_bundles else 0
    logger.info(
        f"V1.1 pipeline complete for video={context.video_id}: "
        f"{teaser_count} teasers, "
        f"{bundle_count} platform bundles, "
        f"{exported_count} exported "
        f"({total_time:.2f}s total)"
    )

    return context


def create_v1_1_pipeline(ai_service, frames_dir: Optional[str] = None):
    """
    Returns a pipeline function matching JobManager's expected signature.

    Usage:
        pipeline_fn = create_v1_1_pipeline(ai_service)
        job_manager.set_pipeline(pipeline_fn)
    """
    async def pipeline(context: VideoContext) -> VideoContext:
        return await run_v1_1_pipeline(context, ai_service, frames_dir)
    return pipeline
