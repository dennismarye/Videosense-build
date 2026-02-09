"""
Circo Video Sense — Local Development Entry Point

Run with:  python main_local.py
Or:        uvicorn main_local:app --reload --port 8000

This starts the service in LOCAL_MODE with:
- No Kafka broker (in-memory queue)
- No S3 (local filesystem)
- No Gemini API (mock AI responses)
- No Slack (notifications logged to console)
- No New Relic (plain logging)

Upload a video via POST /dev/process to trigger the full pipeline.
"""

import asyncio
import logging
import os
import shutil
import signal
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

import uvicorn
from fastapi import FastAPI, File, UploadFile, Form
from fastapi.responses import JSONResponse

from src.config.settings import settings

# Force local mode
os.environ["LOCAL_MODE"] = "true"

# ── Local adapters ────────────────────────────────────────────
from src.local.kafka_service import LocalKafkaService
from src.local.video_analyzer import LocalVideoAnalyzer
from src.local.google_generative_ai import MockGoogleGenerativeService
from src.local.fragment_uploader import LocalFragmentUploader

# ── Reuse existing processing logic ──────────────────────────
from src.video_processor.video_processor import EnhancedVideoProcessor
from src.video_fragmentation.fragment_processor import FragmentProcessor
from src.video_fragmentation.video_segmenter import VideoSegmenter
from src.monitoring.health_check import KafkaMonitorService

# ── V0: Context Graph + Pipeline + GraphQL ────────────────────
from src.context.context_store import ContextStore
from src.context.models import JobRequest
from src.jobs.job_manager import JobManager
from src.jobs.pipeline import run_v0_pipeline
from src.api.router import create_graphql_router

# ── V1: AI Service + V1 Pipeline ──────────────────────────────
from src.local.mock_ai_service import MockAIService
from src.jobs.pipeline_v1 import create_v1_pipeline

# ── V1.1: Teaser Engine Pipeline ──────────────────────────────
from src.jobs.pipeline_v1_1 import create_v1_1_pipeline
from src.context.models import SeriesContext, TeaserMode

# ── V1.2: Content Packaging Pipeline ─────────────────────────
from src.jobs.pipeline_v1_2 import create_v1_2_pipeline

# ── Logging (plain, no New Relic) ─────────────────────────────
LOG_LEVEL = logging.DEBUG
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler()],
)
logging.getLogger("kafka").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# ── Create local storage directories ──────────────────────────
for d in [settings.LOCAL_INPUT_DIR, settings.LOCAL_OUTPUT_DIR, settings.LOCAL_FRAGMENTS_DIR]:
    os.makedirs(d, exist_ok=True)
os.makedirs(settings.OUTPUT_DIR, exist_ok=True)
os.makedirs(settings.TEMP_DIR, exist_ok=True)

# ── Initialize local services ─────────────────────────────────
kafka_service = LocalKafkaService()
monitor = KafkaMonitorService()
monitor.update_kafka_connection(True)  # Always "connected" locally

# Build the video processor with local adapters injected
local_analyzer = LocalVideoAnalyzer(local_input_dir=settings.LOCAL_INPUT_DIR)
mock_ai = MockGoogleGenerativeService()

enhanced_processor = EnhancedVideoProcessor.__new__(EnhancedVideoProcessor)
enhanced_processor.video_analyzer = local_analyzer
enhanced_processor.ai_service = mock_ai
enhanced_processor.output_dir = settings.OUTPUT_DIR
enhanced_processor.temp_dir = settings.TEMP_DIR
enhanced_processor.max_video_size = settings.MAX_VIDEO_SIZE_MB * 1024 * 1024
enhanced_processor.max_duration = settings.MAX_VIDEO_DURATION_SECONDS
enhanced_processor.supported_formats = settings.get_supported_video_formats()
enhanced_processor.ffmpeg_quality = settings.get_ffmpeg_quality_settings()
logger.info("EnhancedVideoProcessor initialized with local adapters")

# Build fragment processor with local adapters
local_uploader = LocalFragmentUploader(output_dir=settings.LOCAL_FRAGMENTS_DIR)

fragment_processor = FragmentProcessor.__new__(FragmentProcessor)
fragment_processor.video_analyzer = local_analyzer
fragment_processor.video_segmenter = VideoSegmenter(temp_dir=settings.FRAGMENTATION_TEMP_DIR)
fragment_processor.s3_uploader = local_uploader
logger.info("FragmentProcessor initialized with local adapters")

# ── Context Graph + Job Manager ────────────────────────────────
context_store = ContextStore()

# V1 pipeline (wraps V0 + adds AI-powered analysis)
mock_ai_service = MockAIService()
v1_pipeline = create_v1_pipeline(mock_ai_service)

# V0 job manager (for /dev/analyze endpoint)
v0_job_manager = JobManager(
    context_store=ContextStore(),  # separate store for V0
    pipeline_fn=run_v0_pipeline,
)

# V1 job manager (primary — for /dev/analyze-v1 and GraphQL)
job_manager = JobManager(
    context_store=context_store,
    pipeline_fn=v1_pipeline,
)
logger.info("V1 Context Graph pipeline initialized (MockAI)")
os.makedirs(settings.CLIP_EXPORT_DIR, exist_ok=True)

# V1.1 pipeline (wraps V1 + adds teaser engine)
v1_1_pipeline = create_v1_1_pipeline(mock_ai_service)

# V1.1 job manager (for /dev/analyze-v1.1)
v1_1_job_manager = JobManager(
    context_store=context_store,  # shared store with V1
    pipeline_fn=v1_1_pipeline,
)
logger.info("V1.1 Teaser Engine pipeline initialized")
os.makedirs(settings.TEASER_EXPORT_DIR, exist_ok=True)

# V1.2 pipeline (wraps V1.1 + adds content packaging)
v1_2_pipeline = create_v1_2_pipeline(mock_ai_service)

# V1.2 job manager (for /dev/analyze-v1.2)
v1_2_job_manager = JobManager(
    context_store=context_store,  # shared store
    pipeline_fn=v1_2_pipeline,
)
logger.info("V1.2 Content Packaging pipeline initialized")

stop_event = threading.Event()


# ── Message processing (same logic, no New Relic decorators) ──

async def process_message(message_data):
    """Process a video message through the full pipeline."""
    try:
        job_id = message_data.get("jobId", "unknown")
        logging.info(f"Processing message for job {job_id}")

        # Stage 1: Safety Check + Video Tagging
        safety_result = await enhanced_processor.process_safety_and_tagging(message_data)

        if safety_result:
            await kafka_service.produce(
                topic="classification.safety_check_passed", data=safety_result
            )
            logging.info(f"Safety result: {safety_result.get('safety_check', {})}")

            safety_check = safety_result.get("safety_check", {})
            content_flag = safety_check.get("contentFlag", "")
            calculated_safety_score = (
                100 if content_flag == "SAFE"
                else (85 if content_flag == "RESTRICT_18+" else 0)
            )

            # Fragmentation (if requested)
            if (
                settings.ENABLE_VIDEO_FRAGMENTATION
                and message_data.get("fragment", False)
                and fragment_processor.should_fragment(
                    message_data, calculated_safety_score, content_flag
                )
            ):
                logging.info(f"Starting fragmentation for job {job_id}")
                fragment_result = await fragment_processor.process_fragmentation(message_data)
                if fragment_result:
                    await kafka_service.produce(
                        topic=settings.FRAGMENT_OUTPUT_TOPIC, data=fragment_result
                    )
                    logging.info(f"Fragmentation complete: {fragment_result.get('totalEpisodes', 0)} episodes")

            # Stage 2: Quality + Description (if safety passed)
            if content_flag in ["SAFE", "RESTRICT_18+"]:
                ai_context = safety_result.get("aiContext", "")
                quality_result = await enhanced_processor.process_quality_and_description(
                    message_data, ai_context=ai_context
                )
                if quality_result:
                    await kafka_service.produce(
                        topic="classification.quality_analysis", data=quality_result
                    )
                    logging.info(f"Quality result: score={quality_result.get('quality_analysis', {}).get('quality_score', '?')}")
            else:
                logging.warning(f"Safety check failed for job {job_id}, skipping quality analysis")

        return safety_result

    except Exception as e:
        logging.error(f"Error processing message: {e}", exc_info=True)
        return {"error": str(e)}


# ── Kafka consumer thread ─────────────────────────────────────

def run_consumer():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            kafka_service.consume(
                topics=[settings.INPUT_TOPIC],
                message_handler=process_message,
                stop_event=stop_event,
            )
        )
    except Exception as e:
        logging.error(f"Consumer error: {e}")
    finally:
        loop.close()


# ── FastAPI Application ───────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("  Circo Video Sense — LOCAL MODE")
    logger.info(f"  Input dir:     {os.path.abspath(settings.LOCAL_INPUT_DIR)}")
    logger.info(f"  Output dir:    {os.path.abspath(settings.LOCAL_OUTPUT_DIR)}")
    logger.info(f"  Fragments dir: {os.path.abspath(settings.LOCAL_FRAGMENTS_DIR)}")
    logger.info("  ──────────────────────────────────────────")
    logger.info("  V1 Pipeline:   ACTIVE (FFmpeg + MockAI)")
    logger.info("  V0 Pipeline:   ACTIVE (FFmpeg-only)")
    logger.info("  V1.1 Teasers:  ACTIVE (Teaser Engine)")
    logger.info("  V1.2 Content:  ACTIVE (Content Packaging)")
    logger.info("  GraphQL IDE:   /graphql")
    logger.info("  V1.2 Analyze:  POST /dev/analyze-v1.2")
    logger.info("  V1.1 Analyze:  POST /dev/analyze-v1.1")
    logger.info("  V1 Analyze:    POST /dev/analyze-v1")
    logger.info("  V0 Analyze:    POST /dev/analyze")
    logger.info("=" * 60)

    consumer_thread = threading.Thread(target=run_consumer, daemon=True)
    consumer_thread.start()

    yield

    logger.info("Shutting down...")
    stop_event.set()
    consumer_thread.join(timeout=5)
    await kafka_service.close_consumer()


app = FastAPI(
    title="Circo Video Sense (Local)",
    description="Local development mode — no external services required",
    version="2.0.0-local",
    lifespan=lifespan,
)

# ── Mount GraphQL API ─────────────────────────────────────────
graphql_router = create_graphql_router(context_store, job_manager)
app.include_router(graphql_router, prefix="/graphql")
logger.info("GraphQL endpoint mounted at /graphql (GraphiQL IDE enabled)")


# ── Health / Metrics ──────────────────────────────────────────

@app.get("/")
async def health_check():
    return JSONResponse(content={
        "status": "healthy",
        "mode": "local",
        "kafka": kafka_service.get_health_status(),
        "input_dir": os.path.abspath(settings.LOCAL_INPUT_DIR),
        "output_dir": os.path.abspath(settings.LOCAL_OUTPUT_DIR),
    })


@app.get("/metrics")
async def get_metrics():
    return JSONResponse(content={
        "service": "circo-video-sense",
        "version": "2.0.0-local",
        "mode": "local",
        "produced_messages": len(kafka_service.get_produced_messages()),
        "features": {
            "safety_check": True,
            "video_tagging": True,
            "quality_analysis": settings.ENABLE_QUALITY_ANALYSIS,
            "description_analysis": settings.ENABLE_DESCRIPTION_ANALYSIS,
            "fragmentation": settings.ENABLE_VIDEO_FRAGMENTATION,
            "gemini_integration": False,
            "slack_notifications": False,
        },
    })


# ── Dev API Endpoints ─────────────────────────────────────────

@app.post("/dev/process")
async def dev_process_video(
    video: UploadFile = File(...),
    title: Optional[str] = Form(""),
    description: Optional[str] = Form(""),
    fragment: Optional[bool] = Form(False),
    fragment_duration: Optional[int] = Form(180),
):
    """
    Upload a video file and run it through the full classification pipeline.

    Returns the combined results from all stages:
    - Safety check + tagging (Stage 1)
    - Quality analysis + description alignment (Stage 2)
    - Fragmentation (if fragment=true)
    """
    job_id = str(uuid.uuid4())

    # Save uploaded file to local input directory
    input_path = os.path.join(settings.LOCAL_INPUT_DIR, f"{job_id}_{video.filename}")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    file_size = os.path.getsize(input_path)
    logger.info(f"[DEV] Saved upload: {input_path} ({file_size} bytes)")

    # Build CircoPost-like message
    message = {
        "jobId": job_id,
        "title": title or "",
        "description": description or "",
        "fragment": fragment,
        "fragmentConfig": {
            "requestedSegmentDuration": fragment_duration,
        },
        "files": [
            {
                "id": job_id,
                "name": video.filename,
                "original": input_path,
                "cachedOriginal": input_path,
                "fileType": "Video",
                "path": input_path,
                "bucket": "local",
            }
        ],
    }

    # Process synchronously (don't go through the queue for dev)
    result = await process_message(message)

    # Gather all produced messages for this job
    produced = [
        m for m in kafka_service.get_produced_messages()
        if m.get("data", {}).get("jobId") == job_id
    ]

    return JSONResponse(content={
        "jobId": job_id,
        "inputFile": input_path,
        "fileSize": file_size,
        "result": result,
        "producedMessages": produced,
    })


@app.post("/dev/analyze")
async def dev_analyze_video(
    video: UploadFile = File(...),
    creator_id: Optional[str] = Form(None),
):
    """
    Upload a video and run V0 Context Graph analysis.

    This is the new Video Sense pipeline — extracts scenes, silence,
    audio tone, thumbnails, quality, pacing, and hook scores into
    a structured Context Graph.

    Query the result via GraphQL at /graphql.
    """
    video_id = str(uuid.uuid4())

    # Save uploaded file
    input_path = os.path.join(settings.LOCAL_INPUT_DIR, f"{video_id}_{video.filename}")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    file_size = os.path.getsize(input_path)
    logger.info(f"[V0] Saved upload: {input_path} ({file_size} bytes)")

    # Run V0 pipeline via JobManager
    request = JobRequest(
        video_id=video_id,
        creator_id=creator_id,
        source_path=input_path,
    )
    context = await job_manager.submit_and_execute(request)

    # Return summary (full graph available via GraphQL)
    return JSONResponse(content={
        "video_id": context.video_id,
        "job_id": context.job_id,
        "status": context.status.value,
        "duration": context.duration,
        "scenes": len(context.scenes),
        "speech_regions": len(context.speech_regions),
        "silence_regions": len(context.silence_regions),
        "thumbnail_candidates": len(context.thumbnail_candidates),
        "quality": {
            "score": context.overall_quality.score if context.overall_quality else None,
            "level": context.overall_quality.level.value if context.overall_quality else None,
        },
        "hook_score": context.hook_score.score if context.hook_score else None,
        "pacing": {
            "score": context.pacing_score.score if context.pacing_score else None,
            "scenes_per_minute": context.pacing_score.scenes_per_minute if context.pacing_score else None,
        },
        "audio_tone": {
            "energy": context.audio_tone.energy if context.audio_tone else None,
            "clarity": context.audio_tone.clarity if context.audio_tone else None,
        },
        "graphql_query": f'{{ videoContext(videoId: "{context.video_id}") {{ status scenes {{ start end confidence }} }} }}',
    })


@app.post("/dev/analyze-v1")
async def dev_analyze_video_v1(
    video: UploadFile = File(...),
    creator_id: Optional[str] = Form(None),
):
    """
    Upload a video and run V1 Context Graph analysis.

    Full Video Sense pipeline: V0 deterministic signals + V1 AI-powered
    analysis (transcript, clips, thumbnails, summary, quality flags).

    Query the full result via GraphQL at /graphql.
    """
    video_id = str(uuid.uuid4())

    # Save uploaded file
    input_path = os.path.join(settings.LOCAL_INPUT_DIR, f"{video_id}_{video.filename}")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    file_size = os.path.getsize(input_path)
    logger.info(f"[V1] Saved upload: {input_path} ({file_size} bytes)")

    # Run V1 pipeline via JobManager
    request = JobRequest(
        video_id=video_id,
        creator_id=creator_id,
        source_path=input_path,
    )
    context = await job_manager.submit_and_execute(request)

    # Return V1 summary (full graph available via GraphQL)
    return JSONResponse(content={
        "video_id": context.video_id,
        "job_id": context.job_id,
        "status": context.status.value,
        "pipeline": "v1",
        "duration": context.duration,
        # V0 signals
        "scenes": len(context.scenes),
        "speech_regions": len(context.speech_regions),
        "silence_regions": len(context.silence_regions),
        # V1 signals
        "suggested_clips": len(context.suggested_clips),
        "thumbnail_candidates": len(context.thumbnail_candidates),
        "quality_flags": len(context.quality_flags),
        "topics": len(context.topics),
        "has_transcript": any(r.transcript for r in context.speech_regions),
        "summary": context.summary,
        "quality": {
            "score": context.overall_quality.score if context.overall_quality else None,
            "level": context.overall_quality.level.value if context.overall_quality else None,
        },
        "hook_score": {
            "score": context.hook_score.score if context.hook_score else None,
            "analysis": context.hook_score.analysis if context.hook_score else None,
        },
        "pacing": {
            "score": context.pacing_score.score if context.pacing_score else None,
            "scenes_per_minute": context.pacing_score.scenes_per_minute if context.pacing_score else None,
        },
        "graphql_query": (
            f'{{ videoContext(videoId: "{context.video_id}") '
            f'{{ status summary suggestedClips {{ clipId start end score rationale format }} '
            f'hookScore {{ score analysis }} }} }}'
        ),
    })


@app.post("/dev/analyze-v1.1")
async def dev_analyze_video_v1_1(
    video: UploadFile = File(...),
    creator_id: Optional[str] = Form(None),
    tier: str = Form("free"),
    series_id: Optional[str] = Form(None),
    series_title: Optional[str] = Form(None),
    episode_number: Optional[int] = Form(None),
    teaser_mode: Optional[str] = Form(None),
):
    """
    Upload a video and run V1.1 Teaser Engine analysis.

    Full pipeline: V0 + V1 + Teaser Selection + Platform Packaging + Export.
    Accepts optional series metadata and monetization tier.
    """
    video_id = str(uuid.uuid4())

    # Save uploaded file
    input_path = os.path.join(settings.LOCAL_INPUT_DIR, f"{video_id}_{video.filename}")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    file_size = os.path.getsize(input_path)
    logger.info(f"[V1.1] Saved upload: {input_path} ({file_size} bytes)")

    # Build job request with series metadata in options
    options = {}
    if series_id:
        options["series_id"] = series_id
        options["series_title"] = series_title or ""
        options["episode_number"] = episode_number or 1
        options["teaser_mode"] = teaser_mode or "trailer"

    request = JobRequest(
        video_id=video_id,
        creator_id=creator_id,
        source_path=input_path,
        tier=tier,
        options=options,
    )

    # Submit first, then propagate tier + series context before execution.
    # JobManager.submit() creates a VideoContext but doesn't copy tier from
    # JobRequest, so we set it manually before the pipeline runs.
    context = await v1_1_job_manager.submit(request)

    if context.status.value != "complete":
        # Attach series context if provided
        if series_id:
            mode = TeaserMode(teaser_mode) if teaser_mode and teaser_mode in [m.value for m in TeaserMode] else TeaserMode.TRAILER
            context.series_context = SeriesContext(
                series_id=series_id,
                series_title=series_title or "",
                episode_number=episode_number or 1,
                teaser_mode=mode,
            )

        # Save updated context before pipeline execution
        await v1_1_job_manager.context_store.save(context)

        # Now execute the pipeline (reads context from store)
        context = await v1_1_job_manager.execute(request.video_id)

    # Return V1.1 summary
    return JSONResponse(content={
        "video_id": context.video_id,
        "job_id": context.job_id,
        "status": context.status.value,
        "pipeline": "v1.1",
        "tier": tier,
        "duration": context.duration,
        # V0+V1 signals
        "scenes": len(context.scenes),
        "suggested_clips": len(context.suggested_clips),
        "summary": context.summary,
        # V1.1 teasers
        "teasers": len(context.teasers),
        "platform_bundles": len(context.platform_bundles),
        "bundles_exported": sum(1 for b in context.platform_bundles if b.exported),
        "series_context": {
            "series_id": context.series_context.series_id,
            "series_title": context.series_context.series_title,
            "episode_number": context.series_context.episode_number,
            "teaser_mode": context.series_context.teaser_mode.value,
        } if context.series_context else None,
        "teaser_details": [
            {
                "teaser_id": t.teaser_id,
                "start": t.start,
                "end": t.end,
                "score": t.teaser_score,
                "mode": t.mode.value,
                "rationale": t.rationale,
            } for t in context.teasers
        ],
        "bundle_details": [
            {
                "bundle_id": b.bundle_id,
                "platform": b.platform.value,
                "title": b.title,
                "hashtags": b.hashtags,
                "format": b.format.value,
                "exported": b.exported,
                "watermarked": b.watermarked,
                "output_path": b.output_path,
            } for b in context.platform_bundles
        ],
        "graphql_query": (
            f'{{ videoContext(videoId: "{context.video_id}") '
            f'{{ status teasers {{ teaserId start end teaserScore mode rationale }} '
            f'platformBundles {{ platform title hashtags exported watermarked }} }} }}'
        ),
    })


@app.post("/dev/analyze-v1.2")
async def dev_analyze_video_v1_2(
    video: UploadFile = File(...),
    creator_id: Optional[str] = Form(None),
    tier: str = Form("free"),
    series_id: Optional[str] = Form(None),
    series_title: Optional[str] = Form(None),
    episode_number: Optional[int] = Form(None),
    teaser_mode: Optional[str] = Form(None),
):
    """
    Upload a video and run V1.2 Content Packaging analysis.

    Full pipeline: V0 + V1 + V1.1 Teasers + V1.2 Content Packaging.
    Returns structured summary including content variants, thumbnail crops,
    and upload presets.
    """
    video_id = str(uuid.uuid4())

    # Save uploaded file
    input_path = os.path.join(settings.LOCAL_INPUT_DIR, f"{video_id}_{video.filename}")
    with open(input_path, "wb") as f:
        shutil.copyfileobj(video.file, f)

    file_size = os.path.getsize(input_path)
    logger.info(f"[V1.2] Saved upload: {input_path} ({file_size} bytes)")

    # Build job request with series metadata in options
    options = {}
    if series_id:
        options["series_id"] = series_id
        options["series_title"] = series_title or ""
        options["episode_number"] = episode_number or 1
        options["teaser_mode"] = teaser_mode or "trailer"

    request = JobRequest(
        video_id=video_id,
        creator_id=creator_id,
        source_path=input_path,
        tier=tier,
        options=options,
    )

    # Submit and propagate series context before execution
    context = await v1_2_job_manager.submit(request)

    if context.status.value != "complete":
        # Attach series context if provided
        if series_id:
            mode = TeaserMode(teaser_mode) if teaser_mode and teaser_mode in [m.value for m in TeaserMode] else TeaserMode.TRAILER
            context.series_context = SeriesContext(
                series_id=series_id,
                series_title=series_title or "",
                episode_number=episode_number or 1,
                teaser_mode=mode,
            )

        await v1_2_job_manager.context_store.save(context)
        context = await v1_2_job_manager.execute(request.video_id)

    # Return V1.2 summary
    return JSONResponse(content={
        "video_id": context.video_id,
        "job_id": context.job_id,
        "status": context.status.value,
        "pipeline": "v1.2",
        "tier": tier,
        "duration": context.duration,
        # V0+V1 signals
        "scenes": len(context.scenes),
        "suggested_clips": len(context.suggested_clips),
        "summary": context.summary,
        # V1.1 teasers
        "teasers": len(context.teasers),
        "platform_bundles": len(context.platform_bundles),
        # V1.2 content packaging
        "content_variants": {
            "titles": len(context.content_variants.titles) if context.content_variants else 0,
            "descriptions": len(context.content_variants.descriptions) if context.content_variants else 0,
        },
        "thumbnail_crops": len(context.thumbnail_crops),
        "upload_presets": len(context.upload_presets),
        "presets_ready": sum(1 for p in context.upload_presets if p.ready),
        "graphql_query": (
            f'{{ videoContext(videoId: "{context.video_id}") '
            f'{{ status contentVariants {{ titles {{ text style platform }} '
            f'descriptions {{ text platform }} }} '
            f'uploadPresets {{ presetId platform ready missing }} }} }}'
        ),
    })


@app.post("/dev/enqueue")
async def dev_enqueue_message(message: dict):
    """
    Inject a raw CircoPost message into the local Kafka queue.
    The consumer thread will pick it up and process it.
    """
    if "jobId" not in message:
        message["jobId"] = str(uuid.uuid4())

    await kafka_service.enqueue(settings.INPUT_TOPIC, message)
    return JSONResponse(content={
        "status": "enqueued",
        "jobId": message["jobId"],
        "topic": settings.INPUT_TOPIC,
    })


@app.get("/dev/messages")
async def dev_list_messages():
    """List all messages produced by the pipeline (for debugging)."""
    return JSONResponse(content={
        "count": len(kafka_service.get_produced_messages()),
        "messages": kafka_service.get_produced_messages(),
    })


@app.delete("/dev/messages")
async def dev_clear_messages():
    """Clear all produced messages."""
    kafka_service.clear_produced_messages()
    return JSONResponse(content={"status": "cleared"})


@app.get("/dev/files")
async def dev_list_files():
    """List all files in local storage directories."""
    def list_dir(path):
        if not os.path.exists(path):
            return []
        result = []
        for root, dirs, files in os.walk(path):
            for f in files:
                full = os.path.join(root, f)
                result.append({
                    "path": full,
                    "size": os.path.getsize(full),
                    "relative": os.path.relpath(full, path),
                })
        return result

    return JSONResponse(content={
        "input": list_dir(settings.LOCAL_INPUT_DIR),
        "output": list_dir(settings.LOCAL_OUTPUT_DIR),
        "fragments": list_dir(settings.LOCAL_FRAGMENTS_DIR),
        "compressed": list_dir(settings.OUTPUT_DIR),
    })


# ── Main ──────────────────────────────────────────────────────

def signal_handler(sig, frame):
    print("\nShutting down...")
    stop_event.set()
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    port = int(os.getenv("PORT", "8000"))
    logger.info(f"Starting local server on http://localhost:{port}")
    logger.info(f"API docs at http://localhost:{port}/docs")

    uvicorn.run(
        "main_local:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        log_level="info",
    )
