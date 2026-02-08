"""
Video Sense GraphQL Schema — Strawberry types + resolvers.

Maps the Pydantic Context Graph models to GraphQL types,
exposes queries for reading contexts, and mutations for
submitting analysis jobs.
"""

import logging
from datetime import datetime
from typing import List, Optional

import strawberry

from src.context.models import (
    VideoContext,
    Scene as SceneModel,
    TimeRange as TimeRangeModel,
    SpeechRegion as SpeechRegionModel,
    MotionPeak as MotionPeakModel,
    AudioTone as AudioToneModel,
    MusicRegion as MusicRegionModel,
    FaceDetection as FaceDetectionModel,
    FramingDetection as FramingDetectionModel,
    CameraMotion as CameraMotionModel,
    QualityFlag as QualityFlagModel,
    OverallQuality as OverallQualityModel,
    SuggestedClip as SuggestedClipModel,
    ThumbnailCandidate as ThumbnailCandidateModel,
    HookScore as HookScoreModel,
    PacingScore as PacingScoreModel,
    SafetyResult as SafetyResultModel,
    Topic as TopicModel,
    Entity as EntityModel,
    NarrativeBeat as NarrativeBeatModel,
    JobStatus,
)

logger = logging.getLogger(__name__)


# ── GraphQL Types ────────────────────────────────────────────

@strawberry.type
class Scene:
    start: float
    end: float
    description: Optional[str]
    confidence: float


@strawberry.type
class TimeRange:
    start: float
    end: float


@strawberry.type
class SpeechRegion:
    start: float
    end: float
    transcript: Optional[str]
    keywords: List[str]


@strawberry.type
class MotionPeak:
    timestamp: float
    intensity: float


@strawberry.type
class AudioTone:
    energy: float
    sentiment: float
    clarity: float


@strawberry.type
class MusicRegion:
    start: float
    end: float
    genre: Optional[str]
    bpm: Optional[float]


@strawberry.type
class OverallQuality:
    score: int
    level: str
    resolution: Optional[str]
    fps: Optional[float]
    codec: Optional[str]
    has_audio: bool
    issues: List[str]


@strawberry.type
class SuggestedClip:
    clip_id: str
    start: float
    end: float
    score: float
    rationale: Optional[str]
    format: str


@strawberry.type
class ThumbnailCandidate:
    timestamp: float
    score: float
    reasons: List[str]
    frame_path: Optional[str]


@strawberry.type
class HookScore:
    score: float
    analysis: Optional[str]


@strawberry.type
class PacingScore:
    score: float
    scenes_per_minute: float
    analysis: Optional[str]


@strawberry.type
class SafetyResult:
    content_flag: str
    reason: Optional[str]


@strawberry.type
class Topic:
    label: str
    confidence: float
    timestamps: List[float]


@strawberry.type
class Entity:
    name: str
    type: str
    timestamps: List[float]


@strawberry.type
class NarrativeBeat:
    type: str
    timestamp: float
    description: Optional[str]


# ── V1 GraphQL Types ─────────────────────────────────────────

@strawberry.type
class QualityFlag:
    type: str
    timestamp: float
    severity: float


@strawberry.type
class ClipFeedbackType:
    clip_id: str
    action: str
    exported_format: Optional[str]
    timestamp: str


@strawberry.type
class TranscriptSegment:
    start: float
    end: float
    text: str
    keywords: List[str]


@strawberry.type
class ExportResult:
    clip_id: str
    output_path: str
    format: str
    duration: float
    success: bool
    error: Optional[str]


# ── V1.1 Teaser Engine GraphQL Types ────────────────────────

@strawberry.type
class TeaserType:
    teaser_id: str
    source_clip_id: str
    start: float
    end: float
    teaser_score: float
    mode: str
    rationale: Optional[str]
    narrative_alignment: Optional[str]


@strawberry.type
class PlatformBundleType:
    bundle_id: str
    teaser_id: str
    platform: str
    title: str
    hashtags: List[str]
    format: str
    output_path: Optional[str]
    duration: float
    exported: bool
    error: Optional[str]
    watermarked: bool


@strawberry.type
class SeriesContextType:
    series_id: str
    series_title: str
    episode_number: int
    total_episodes: Optional[int]
    teaser_mode: str


@strawberry.type
class VideoContextType:
    """The complete Context Graph for a video — the core GraphQL type."""

    video_id: str
    job_id: str
    status: str
    duration: float
    file_size: int
    source_path: Optional[str]
    creator_id: Optional[str]
    created_at: str
    updated_at: str

    # Safety
    safety: Optional[SafetyResult]

    # Timeline signals
    scenes: List[Scene]
    silence_regions: List[TimeRange]
    speech_regions: List[SpeechRegion]
    motion_peaks: List[MotionPeak]

    # Semantic signals
    topics: List[Topic]
    entities: List[Entity]
    narrative_beats: List[NarrativeBeat]

    # Audio signals
    audio_tone: Optional[AudioTone]
    music_regions: List[MusicRegion]

    # Quality
    quality_flags: List[QualityFlag]
    overall_quality: Optional[OverallQuality]

    # Artifacts
    suggested_clips: List[SuggestedClip]
    thumbnail_candidates: List[ThumbnailCandidate]
    summary: Optional[str]
    hook_score: Optional[HookScore]
    pacing_score: Optional[PacingScore]

    # V1.1 Teaser Engine
    teasers: List[TeaserType]
    platform_bundles: List[PlatformBundleType]
    series_context: Optional[SeriesContextType]


@strawberry.type
class JobSubmitResult:
    job_id: str
    video_id: str
    status: str
    message: str


@strawberry.type
class PipelineStats:
    total_jobs: int
    active_jobs: int
    complete: int
    failed: int
    queued: int


# ── Converter: Pydantic → Strawberry ─────────────────────────

def _convert_context(ctx: VideoContext) -> VideoContextType:
    """Convert a Pydantic VideoContext to the Strawberry GraphQL type."""
    return VideoContextType(
        video_id=ctx.video_id,
        job_id=ctx.job_id,
        status=ctx.status.value,
        duration=ctx.duration,
        file_size=ctx.file_size,
        source_path=ctx.source_path,
        creator_id=ctx.creator_id,
        created_at=ctx.created_at.isoformat(),
        updated_at=ctx.updated_at.isoformat(),
        # Safety
        safety=SafetyResult(
            content_flag=ctx.safety.content_flag.value,
            reason=ctx.safety.reason,
        ) if ctx.safety else None,
        # Timeline
        scenes=[
            Scene(start=s.start, end=s.end, description=s.description, confidence=s.confidence)
            for s in ctx.scenes
        ],
        silence_regions=[
            TimeRange(start=r.start, end=r.end)
            for r in ctx.silence_regions
        ],
        speech_regions=[
            SpeechRegion(start=r.start, end=r.end, transcript=r.transcript, keywords=r.keywords)
            for r in ctx.speech_regions
        ],
        motion_peaks=[
            MotionPeak(timestamp=m.timestamp, intensity=m.intensity)
            for m in ctx.motion_peaks
        ],
        # Semantic
        topics=[
            Topic(label=t.label, confidence=t.confidence, timestamps=t.timestamps)
            for t in ctx.topics
        ],
        entities=[
            Entity(name=e.name, type=e.type, timestamps=e.timestamps)
            for e in ctx.entities
        ],
        narrative_beats=[
            NarrativeBeat(type=n.type, timestamp=n.timestamp, description=n.description)
            for n in ctx.narrative_beats
        ],
        # Audio
        audio_tone=AudioTone(
            energy=ctx.audio_tone.energy,
            sentiment=ctx.audio_tone.sentiment,
            clarity=ctx.audio_tone.clarity,
        ) if ctx.audio_tone else None,
        music_regions=[
            MusicRegion(start=m.start, end=m.end, genre=m.genre, bpm=m.bpm)
            for m in ctx.music_regions
        ],
        # Quality
        quality_flags=[
            QualityFlag(type=f.type, timestamp=f.timestamp, severity=f.severity)
            for f in ctx.quality_flags
        ],
        overall_quality=OverallQuality(
            score=ctx.overall_quality.score,
            level=ctx.overall_quality.level.value,
            resolution=ctx.overall_quality.resolution,
            fps=ctx.overall_quality.fps,
            codec=ctx.overall_quality.codec,
            has_audio=ctx.overall_quality.has_audio,
            issues=ctx.overall_quality.issues,
        ) if ctx.overall_quality else None,
        # Artifacts
        suggested_clips=[
            SuggestedClip(
                clip_id=c.clip_id, start=c.start, end=c.end,
                score=c.score, rationale=c.rationale, format=c.format.value,
            )
            for c in ctx.suggested_clips
        ],
        thumbnail_candidates=[
            ThumbnailCandidate(
                timestamp=t.timestamp, score=t.score,
                reasons=t.reasons, frame_path=t.frame_path,
            )
            for t in ctx.thumbnail_candidates
        ],
        summary=ctx.summary,
        hook_score=HookScore(
            score=ctx.hook_score.score, analysis=ctx.hook_score.analysis,
        ) if ctx.hook_score else None,
        pacing_score=PacingScore(
            score=ctx.pacing_score.score,
            scenes_per_minute=ctx.pacing_score.scenes_per_minute,
            analysis=ctx.pacing_score.analysis,
        ) if ctx.pacing_score else None,
        # V1.1 Teaser Engine
        teasers=[
            TeaserType(
                teaser_id=t.teaser_id, source_clip_id=t.source_clip_id,
                start=t.start, end=t.end, teaser_score=t.teaser_score,
                mode=t.mode.value, rationale=t.rationale,
                narrative_alignment=t.narrative_alignment,
            ) for t in ctx.teasers
        ],
        platform_bundles=[
            PlatformBundleType(
                bundle_id=b.bundle_id, teaser_id=b.teaser_id,
                platform=b.platform.value, title=b.title,
                hashtags=b.hashtags, format=b.format.value,
                output_path=b.output_path, duration=b.duration,
                exported=b.exported, error=b.error,
                watermarked=b.watermarked,
            ) for b in ctx.platform_bundles
        ],
        series_context=SeriesContextType(
            series_id=ctx.series_context.series_id,
            series_title=ctx.series_context.series_title,
            episode_number=ctx.series_context.episode_number,
            total_episodes=ctx.series_context.total_episodes,
            teaser_mode=ctx.series_context.teaser_mode.value,
        ) if ctx.series_context else None,
    )


# ── Query + Mutation Resolvers ───────────────────────────────
# These are created by the factory function below, which receives
# the runtime dependencies (context_store, job_manager).

def create_schema(context_store, job_manager):
    """
    Factory that creates the Strawberry schema with bound dependencies.

    Returns a strawberry.Schema ready to mount on FastAPI.
    """

    @strawberry.type
    class Query:
        @strawberry.field(description="Get the Context Graph for a video by ID")
        async def video_context(self, video_id: str) -> Optional[VideoContextType]:
            ctx = await context_store.get_by_video_id(video_id)
            if ctx:
                return _convert_context(ctx)
            return None

        @strawberry.field(description="Get context by job ID")
        async def job_context(self, job_id: str) -> Optional[VideoContextType]:
            ctx = await context_store.get_by_job_id(job_id)
            if ctx:
                return _convert_context(ctx)
            return None

        @strawberry.field(description="List all processed videos")
        async def all_contexts(self, limit: int = 50) -> List[VideoContextType]:
            contexts = await context_store.list_all(limit=limit)
            return [_convert_context(c) for c in contexts]

        @strawberry.field(description="Pipeline statistics")
        async def pipeline_stats(self) -> PipelineStats:
            stats = job_manager.get_stats()
            by_status = stats.get("by_status", {})
            return PipelineStats(
                total_jobs=stats.get("total_jobs", 0),
                active_jobs=stats.get("active_jobs", 0),
                complete=by_status.get("complete", 0),
                failed=by_status.get("failed", 0),
                queued=by_status.get("queued", 0),
            )

        # ── V1 Queries ──────────────────────────────────────

        @strawberry.field(description="Get suggested clips for a video, ranked by score")
        async def suggested_clips(
            self, video_id: str, limit: int = 15, format: Optional[str] = None,
        ) -> List[SuggestedClip]:
            ctx = await context_store.get_by_video_id(video_id)
            if not ctx:
                return []
            clips = ctx.suggested_clips
            if format:
                clips = [c for c in clips if c.format.value == format]
            return [
                SuggestedClip(
                    clip_id=c.clip_id, start=c.start, end=c.end,
                    score=c.score, rationale=c.rationale, format=c.format.value,
                )
                for c in clips[:limit]
            ]

        @strawberry.field(description="Get transcript with timestamps")
        async def transcript(self, video_id: str) -> List[TranscriptSegment]:
            ctx = await context_store.get_by_video_id(video_id)
            if not ctx:
                return []
            return [
                TranscriptSegment(
                    start=r.start, end=r.end,
                    text=r.transcript or "", keywords=r.keywords,
                )
                for r in ctx.speech_regions if r.transcript
            ]

        @strawberry.field(description="Get ranked thumbnail candidates")
        async def thumbnail_candidates(
            self, video_id: str, limit: int = 5,
        ) -> List[ThumbnailCandidate]:
            ctx = await context_store.get_by_video_id(video_id)
            if not ctx:
                return []
            return [
                ThumbnailCandidate(
                    timestamp=t.timestamp, score=t.score,
                    reasons=t.reasons, frame_path=t.frame_path,
                )
                for t in ctx.thumbnail_candidates[:limit]
            ]

        # ── V1.1 Queries ─────────────────────────────────────

        @strawberry.field(description="Get teasers for a video")
        async def teasers(self, video_id: str) -> List[TeaserType]:
            ctx = await context_store.get_by_video_id(video_id)
            if not ctx:
                return []
            return [
                TeaserType(
                    teaser_id=t.teaser_id, source_clip_id=t.source_clip_id,
                    start=t.start, end=t.end, teaser_score=t.teaser_score,
                    mode=t.mode.value, rationale=t.rationale,
                    narrative_alignment=t.narrative_alignment,
                ) for t in ctx.teasers
            ]

        @strawberry.field(description="Get platform bundles for a video")
        async def platform_bundles(
            self, video_id: str, platform: Optional[str] = None,
        ) -> List[PlatformBundleType]:
            ctx = await context_store.get_by_video_id(video_id)
            if not ctx:
                return []
            bundles = ctx.platform_bundles
            if platform:
                bundles = [b for b in bundles if b.platform.value == platform]
            return [
                PlatformBundleType(
                    bundle_id=b.bundle_id, teaser_id=b.teaser_id,
                    platform=b.platform.value, title=b.title,
                    hashtags=b.hashtags, format=b.format.value,
                    output_path=b.output_path, duration=b.duration,
                    exported=b.exported, error=b.error,
                    watermarked=b.watermarked,
                ) for b in bundles
            ]

    @strawberry.type
    class Mutation:
        @strawberry.mutation(description="Submit a video for V0 analysis")
        async def analyze_video(
            self,
            video_id: str,
            source_path: str,
            creator_id: Optional[str] = None,
            tier: str = "free",
        ) -> JobSubmitResult:
            from src.context.models import JobRequest

            request = JobRequest(
                video_id=video_id,
                creator_id=creator_id,
                source_path=source_path,
                tier=tier,
            )

            context = await job_manager.submit_and_execute(request)

            return JobSubmitResult(
                job_id=context.job_id,
                video_id=context.video_id,
                status=context.status.value,
                message=f"Analysis {context.status.value}",
            )

        # ── V1 Mutations ─────────────────────────────────────

        @strawberry.mutation(description="Approve a suggested clip")
        async def approve_clip(
            self, video_id: str, clip_id: str,
        ) -> ClipFeedbackType:
            from src.context.models import ClipFeedback, FeedbackAction

            feedback = ClipFeedback(
                clip_id=clip_id,
                action=FeedbackAction.APPROVED,
            )
            ctx = await context_store.get_by_video_id(video_id)
            if ctx:
                ctx.clip_feedback.append(feedback)
                await context_store.save(ctx)

            return ClipFeedbackType(
                clip_id=clip_id,
                action="approved",
                exported_format=None,
                timestamp=feedback.timestamp.isoformat(),
            )

        @strawberry.mutation(description="Reject a suggested clip")
        async def reject_clip(
            self, video_id: str, clip_id: str,
        ) -> ClipFeedbackType:
            from src.context.models import ClipFeedback, FeedbackAction

            feedback = ClipFeedback(
                clip_id=clip_id,
                action=FeedbackAction.REJECTED,
            )
            ctx = await context_store.get_by_video_id(video_id)
            if ctx:
                ctx.clip_feedback.append(feedback)
                await context_store.save(ctx)

            return ClipFeedbackType(
                clip_id=clip_id,
                action="rejected",
                exported_format=None,
                timestamp=feedback.timestamp.isoformat(),
            )

        @strawberry.mutation(description="Export a clip to a specific format")
        async def export_clip(
            self, video_id: str, clip_id: str, format: str = "16:9",
        ) -> ExportResult:
            from src.actions.clip_operations import extract_clip
            from src.context.models import ClipFormat
            from src.config.settings import settings

            ctx = await context_store.get_by_video_id(video_id)
            if not ctx or not ctx.source_path:
                return ExportResult(
                    clip_id=clip_id, output_path="", format=format,
                    duration=0, success=False, error="Video context not found",
                )

            clip = next((c for c in ctx.suggested_clips if c.clip_id == clip_id), None)
            if not clip:
                return ExportResult(
                    clip_id=clip_id, output_path="", format=format,
                    duration=0, success=False, error=f"Clip {clip_id} not found",
                )

            # Override format if requested
            format_map = {"16:9": ClipFormat.LANDSCAPE, "9:16": ClipFormat.PORTRAIT, "1:1": ClipFormat.SQUARE}
            if format in format_map:
                clip.format = format_map[format]

            result = await extract_clip(ctx.source_path, clip, settings.CLIP_EXPORT_DIR)

            return ExportResult(
                clip_id=result["clip_id"],
                output_path=result["output_path"],
                format=result["format"],
                duration=result["duration"],
                success=result["success"],
                error=result.get("error"),
            )

        # ── V1.1 Mutations ────────────────────────────────────

        @strawberry.mutation(description="Generate teasers for an already-analyzed video (V1.1)")
        async def generate_teasers(self, video_id: str, tier: str = "free") -> List[TeaserType]:
            ctx = await context_store.get_by_video_id(video_id)
            if not ctx or not ctx.suggested_clips:
                return []
            # Import and run teaser generation on-demand
            from src.actions.teaser_selector import select_teasers
            from src.actions.platform_packager import package_for_platforms
            from src.actions.teaser_exporter import export_teasers
            from src.context.models import MonetizationTier
            from src.config.settings import settings

            # Idempotency: if teasers already exist, return them
            if ctx.teasers:
                return [
                    TeaserType(
                        teaser_id=t.teaser_id, source_clip_id=t.source_clip_id,
                        start=t.start, end=t.end, teaser_score=t.teaser_score,
                        mode=t.mode.value, rationale=t.rationale,
                        narrative_alignment=t.narrative_alignment,
                    ) for t in ctx.teasers
                ]

            tier_enum = MonetizationTier(tier) if tier in [t.value for t in MonetizationTier] else MonetizationTier.FREE

            teasers = await select_teasers(ctx, None, max_teasers=settings.TEASER_MAX_COUNT)
            ctx.teasers = teasers

            ctx.platform_bundles = await package_for_platforms(teasers, ctx, None, tier=tier_enum)

            ctx.platform_bundles = await export_teasers(
                ctx.platform_bundles, teasers,
                ctx.source_path or "", settings.TEASER_EXPORT_DIR,
            )

            await context_store.save(ctx)
            return [
                TeaserType(
                    teaser_id=t.teaser_id, source_clip_id=t.source_clip_id,
                    start=t.start, end=t.end, teaser_score=t.teaser_score,
                    mode=t.mode.value, rationale=t.rationale,
                    narrative_alignment=t.narrative_alignment,
                ) for t in ctx.teasers
            ]

    schema = strawberry.Schema(query=Query, mutation=Mutation)
    return schema
