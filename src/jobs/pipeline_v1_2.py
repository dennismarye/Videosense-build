"""
V1.2 Content Packaging Pipeline — extends V1.1 with content packaging.

Runs the full V1.1 pipeline first (V0 deterministic + AI-enhanced + teaser
engine, steps 1-18), then layers on content packaging steps: content
generation, hashtag normalization, thumbnail crop recommendations, and
upload preset assembly.

V1.2 steps are fault-tolerant: if any content packaging step fails, the
pipeline logs the error and continues. V1.1 data is always preserved.
The pipeline only returns FAILED status if V1 itself fails (inherited
from V1.1 behavior).

Step layout:
  Steps 1-15:  V1 pipeline (V0 deterministic + AI-enhanced)
  Steps 16-18: V1.1 teaser engine (fault-tolerant)
  Steps 19-22: V1.2 content packaging (fault-tolerant)
"""

import logging
import time
from typing import Optional

from src.context.models import VideoContext, JobStatus
from src.jobs.pipeline_v1_1 import run_v1_1_pipeline

logger = logging.getLogger(__name__)


async def run_v1_2_pipeline(
    context: VideoContext,
    ai_service,
    frames_dir: Optional[str] = None,
) -> VideoContext:
    """
    Execute the V1.2 content packaging pipeline.

    Steps 1-18:  V1.1 pipeline (V0 + AI + teaser engine)
    Steps 19-22: Content packaging (fault-tolerant)

    Args:
        context: VideoContext with source_path populated.
        ai_service: An AIService implementation (real or mock).
        frames_dir: Optional directory for extracted thumbnail frames.

    Returns:
        Populated VideoContext (status is set by JobManager, not here).
    """
    pipeline_start = time.time()

    logger.info(f"Starting V1.2 pipeline for video={context.video_id}")

    # ── Steps 1-18: V1.1 pipeline (V0 + AI + teaser engine) ──
    context = await run_v1_1_pipeline(context, ai_service, frames_dir)

    if context.status == JobStatus.FAILED:
        logger.error(
            f"V1.1 pipeline failed for video={context.video_id}, "
            f"skipping content packaging steps"
        )
        return context

    # ── Step 19: Content generation ─────────────────────────────
    logger.info("[19/22] Generating content variants...")
    step_start = time.time()
    try:
        from src.actions.content_generator import generate_content

        context.content_variants = await generate_content(
            context, ai_service,
        )
        title_count = len(context.content_variants.titles) if context.content_variants else 0
        desc_count = len(context.content_variants.descriptions) if context.content_variants else 0
        logger.info(
            f"  Generated {title_count} titles, {desc_count} descriptions "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Content generation failed: {e}", exc_info=True)

    # ── Step 20: Hashtag normalization ──────────────────────────
    logger.info("[20/22] Normalizing hashtags...")
    step_start = time.time()
    hashtag_sets = []
    try:
        from src.actions.hashtag_normalizer import normalize_hashtags

        hashtag_sets = await normalize_hashtags(context, ai_service)
        total_tags = sum(len(hs.hashtags) for hs in hashtag_sets)
        logger.info(
            f"  Normalized {total_tags} hashtags across "
            f"{len(hashtag_sets)} platform sets "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Hashtag normalization failed: {e}", exc_info=True)

    # ── Step 21: Thumbnail crop recommendations ─────────────────
    logger.info("[21/22] Recommending thumbnail crops...")
    step_start = time.time()
    try:
        from src.actions.thumbnail_cropper import recommend_crops

        context.thumbnail_crops = await recommend_crops(context, ai_service)
        logger.info(
            f"  Generated {len(context.thumbnail_crops)} crop recommendations "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Thumbnail crop recommendation failed: {e}", exc_info=True)

    # ── Step 22: Upload preset assembly ────────────────────────
    logger.info("[22/22] Building upload presets...")
    step_start = time.time()
    try:
        from src.actions.upload_preset import build_upload_presets_with_hashtags

        context.upload_presets = build_upload_presets_with_hashtags(
            context,
            hashtag_sets,
            thumbnail_crops=context.thumbnail_crops,
        )
        ready_count = sum(1 for p in context.upload_presets if p.ready)
        logger.info(
            f"  Built {len(context.upload_presets)} upload presets "
            f"({ready_count} ready) "
            f"({time.time() - step_start:.2f}s)"
        )
    except Exception as e:
        logger.error(f"  Upload preset assembly failed: {e}", exc_info=True)

    # ── Done ──────────────────────────────────────────────────
    total_time = time.time() - pipeline_start
    teaser_count = len(context.teasers)
    bundle_count = len(context.platform_bundles)
    content_count = (
        len(context.content_variants.titles) if context.content_variants else 0
    )
    crop_count = len(context.thumbnail_crops)
    preset_count = len(context.upload_presets)

    logger.info(
        f"V1.2 pipeline complete for video={context.video_id}: "
        f"{teaser_count} teasers, "
        f"{bundle_count} platform bundles, "
        f"{content_count} title variants, "
        f"{crop_count} crop recommendations, "
        f"{preset_count} upload presets "
        f"({total_time:.2f}s total)"
    )

    return context


def create_v1_2_pipeline(ai_service, frames_dir: Optional[str] = None):
    """
    Returns a pipeline function matching JobManager's expected signature.

    Usage:
        pipeline_fn = create_v1_2_pipeline(ai_service)
        job_manager.set_pipeline(pipeline_fn)
    """
    async def pipeline(context: VideoContext) -> VideoContext:
        return await run_v1_2_pipeline(context, ai_service, frames_dir)
    return pipeline
