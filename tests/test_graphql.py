"""Tests for the GraphQL schema — queries and mutations."""

import pytest
import strawberry

from src.api.schema import create_schema, _convert_context
from src.context.models import (
    AudioTone,
    ClipFormat,
    HookScore,
    JobRequest,
    NarrativeBeat,
    OverallQuality,
    QualityLevel,
    Scene,
    SpeechRegion,
    SuggestedClip,
    Teaser,
    TeaserMode,
    PlatformBundle,
    Platform,
    SeriesContext,
    ThumbnailCandidate,
    TimeRange,
    Topic,
    VideoContext,
)
from src.context.context_store import ContextStore
from src.jobs.job_manager import JobManager


# ── Helpers ──────────────────────────────────────────────────

async def _noop_pipeline(context: VideoContext) -> VideoContext:
    context.duration = 10.0
    return context


@pytest.fixture
def gql_setup():
    """Create schema, store, and manager together."""
    store = ContextStore()
    mgr = JobManager(store, _noop_pipeline)
    schema = create_schema(store, mgr)
    return schema, store, mgr


# ── Converter tests ──────────────────────────────────────────

class TestConvertContext:
    def test_basic_conversion(self):
        ctx = VideoContext(video_id="v1", duration=30.0)
        gql = _convert_context(ctx)
        assert gql.video_id == "v1"
        assert gql.duration == 30.0
        assert gql.status == "queued"

    def test_scenes_converted(self):
        ctx = VideoContext(
            video_id="v1",
            scenes=[Scene(start=0.0, end=10.0, confidence=0.9)],
        )
        gql = _convert_context(ctx)
        assert len(gql.scenes) == 1
        assert gql.scenes[0].start == 0.0

    def test_clips_format_is_string(self):
        ctx = VideoContext(
            video_id="v1",
            suggested_clips=[
                SuggestedClip(clip_id="c1", start=0.0, end=10.0, score=0.8, format=ClipFormat.PORTRAIT)
            ],
        )
        gql = _convert_context(ctx)
        assert gql.suggested_clips[0].format == "9:16"

    def test_teasers_converted(self):
        ctx = VideoContext(
            video_id="v1",
            teasers=[
                Teaser(teaser_id="t1", source_clip_id="c1", start=0.0, end=20.0,
                       teaser_score=0.8, mode=TeaserMode.TRAILER)
            ],
        )
        gql = _convert_context(ctx)
        assert len(gql.teasers) == 1
        assert gql.teasers[0].mode == "trailer"

    def test_platform_bundles_converted(self):
        ctx = VideoContext(
            video_id="v1",
            platform_bundles=[
                PlatformBundle(
                    bundle_id="b1", teaser_id="t1", platform=Platform.TIKTOK,
                    title="Test", format=ClipFormat.PORTRAIT, watermarked=True,
                )
            ],
        )
        gql = _convert_context(ctx)
        assert len(gql.platform_bundles) == 1
        assert gql.platform_bundles[0].platform == "tiktok"
        assert gql.platform_bundles[0].watermarked is True

    def test_series_context_converted(self):
        ctx = VideoContext(
            video_id="v1",
            series_context=SeriesContext(
                series_id="s1", series_title="Show",
                episode_number=3, teaser_mode=TeaserMode.TRAILER,
            ),
        )
        gql = _convert_context(ctx)
        assert gql.series_context is not None
        assert gql.series_context.teaser_mode == "trailer"
        assert gql.series_context.episode_number == 3

    def test_null_optionals(self):
        ctx = VideoContext(video_id="v1")
        gql = _convert_context(ctx)
        assert gql.safety is None
        assert gql.audio_tone is None
        assert gql.overall_quality is None
        assert gql.hook_score is None
        assert gql.series_context is None

    def test_overall_quality_converted(self):
        ctx = VideoContext(
            video_id="v1",
            overall_quality=OverallQuality(
                score=80, level=QualityLevel.GOOD,
                resolution="1920x1080", fps=30.0, codec="h264",
                has_audio=True, issues=["low_audio"],
            ),
        )
        gql = _convert_context(ctx)
        assert gql.overall_quality.score == 80
        assert gql.overall_quality.level == "GOOD"
        assert gql.overall_quality.issues == ["low_audio"]


# ── Query tests ──────────────────────────────────────────────

class TestQueries:
    async def test_video_context_query(self, gql_setup):
        schema, store, mgr = gql_setup
        ctx = VideoContext(video_id="v1", duration=30.0)
        await store.save(ctx)

        result = await schema.execute(
            'query { videoContext(videoId: "v1") { videoId duration status } }'
        )
        assert result.errors is None
        assert result.data["videoContext"]["videoId"] == "v1"
        assert result.data["videoContext"]["duration"] == 30.0

    async def test_video_context_not_found(self, gql_setup):
        schema, store, mgr = gql_setup
        result = await schema.execute(
            'query { videoContext(videoId: "missing") { videoId } }'
        )
        assert result.errors is None
        assert result.data["videoContext"] is None

    async def test_all_contexts_query(self, gql_setup):
        schema, store, mgr = gql_setup
        await store.save(VideoContext(video_id="v1"))
        await store.save(VideoContext(video_id="v2"))

        result = await schema.execute(
            "query { allContexts { videoId } }"
        )
        assert result.errors is None
        assert len(result.data["allContexts"]) == 2

    async def test_pipeline_stats_query(self, gql_setup):
        schema, store, mgr = gql_setup
        result = await schema.execute(
            "query { pipelineStats { totalJobs activeJobs } }"
        )
        assert result.errors is None
        assert result.data["pipelineStats"]["totalJobs"] == 0

    async def test_suggested_clips_query(self, gql_setup):
        schema, store, mgr = gql_setup
        ctx = VideoContext(
            video_id="v1",
            suggested_clips=[
                SuggestedClip(clip_id="c1", start=0.0, end=10.0, score=0.8, format=ClipFormat.LANDSCAPE),
            ],
        )
        await store.save(ctx)

        result = await schema.execute(
            'query { suggestedClips(videoId: "v1") { clipId score format } }'
        )
        assert result.errors is None
        assert len(result.data["suggestedClips"]) == 1
        assert result.data["suggestedClips"][0]["format"] == "16:9"

    async def test_transcript_query(self, gql_setup):
        schema, store, mgr = gql_setup
        ctx = VideoContext(
            video_id="v1",
            speech_regions=[
                SpeechRegion(start=0.0, end=5.0, transcript="Hello world", keywords=["hello"]),
            ],
        )
        await store.save(ctx)

        result = await schema.execute(
            'query { transcript(videoId: "v1") { start end text keywords } }'
        )
        assert result.errors is None
        assert result.data["transcript"][0]["text"] == "Hello world"

    async def test_teasers_query(self, gql_setup):
        schema, store, mgr = gql_setup
        ctx = VideoContext(
            video_id="v1",
            teasers=[
                Teaser(teaser_id="t1", source_clip_id="c1", start=0.0, end=20.0,
                       teaser_score=0.8, mode=TeaserMode.STANDARD),
            ],
        )
        await store.save(ctx)

        result = await schema.execute(
            'query { teasers(videoId: "v1") { teaserId teaserScore mode } }'
        )
        assert result.errors is None
        assert len(result.data["teasers"]) == 1
        assert result.data["teasers"][0]["mode"] == "standard"

    async def test_platform_bundles_query(self, gql_setup):
        schema, store, mgr = gql_setup
        ctx = VideoContext(
            video_id="v1",
            platform_bundles=[
                PlatformBundle(
                    bundle_id="b1", teaser_id="t1", platform=Platform.CIRCO,
                    title="Test", format=ClipFormat.LANDSCAPE,
                ),
            ],
        )
        await store.save(ctx)

        result = await schema.execute(
            'query { platformBundles(videoId: "v1") { bundleId platform title } }'
        )
        assert result.errors is None
        assert result.data["platformBundles"][0]["platform"] == "circo"

    async def test_platform_bundles_filter_by_platform(self, gql_setup):
        schema, store, mgr = gql_setup
        ctx = VideoContext(
            video_id="v1",
            platform_bundles=[
                PlatformBundle(bundle_id="b1", teaser_id="t1", platform=Platform.CIRCO,
                               title="Circo", format=ClipFormat.LANDSCAPE),
                PlatformBundle(bundle_id="b2", teaser_id="t1", platform=Platform.TIKTOK,
                               title="TikTok", format=ClipFormat.PORTRAIT),
            ],
        )
        await store.save(ctx)

        result = await schema.execute(
            'query { platformBundles(videoId: "v1", platform: "circo") { platform } }'
        )
        assert result.errors is None
        assert len(result.data["platformBundles"]) == 1
        assert result.data["platformBundles"][0]["platform"] == "circo"


# ── Mutation tests ───────────────────────────────────────────

class TestMutations:
    async def test_analyze_video_mutation(self, gql_setup):
        schema, store, mgr = gql_setup
        result = await schema.execute(
            """
            mutation {
                analyzeVideo(videoId: "v1", sourcePath: "/tmp/v.mp4") {
                    jobId videoId status message
                }
            }
            """
        )
        assert result.errors is None
        data = result.data["analyzeVideo"]
        assert data["videoId"] == "v1"
        assert data["status"] == "complete"

    async def test_approve_clip_mutation(self, gql_setup):
        schema, store, mgr = gql_setup
        ctx = VideoContext(video_id="v1")
        await store.save(ctx)

        result = await schema.execute(
            """
            mutation {
                approveClip(videoId: "v1", clipId: "c1") {
                    clipId action
                }
            }
            """
        )
        assert result.errors is None
        assert result.data["approveClip"]["action"] == "approved"

        # Verify feedback was saved
        updated = await store.get_by_video_id("v1")
        assert len(updated.clip_feedback) == 1

    async def test_reject_clip_mutation(self, gql_setup):
        schema, store, mgr = gql_setup
        ctx = VideoContext(video_id="v1")
        await store.save(ctx)

        result = await schema.execute(
            """
            mutation {
                rejectClip(videoId: "v1", clipId: "c1") {
                    clipId action
                }
            }
            """
        )
        assert result.errors is None
        assert result.data["rejectClip"]["action"] == "rejected"

    async def test_generate_teasers_idempotent(self, gql_setup):
        schema, store, mgr = gql_setup
        # Create a context with clips AND pre-existing teasers
        ctx = VideoContext(
            video_id="v1",
            duration=120.0,
            suggested_clips=[
                SuggestedClip(clip_id="c1", start=0.0, end=20.0, score=0.8),
            ],
            teasers=[
                Teaser(
                    teaser_id="existing-t1", source_clip_id="c1",
                    start=0.0, end=20.0, teaser_score=0.5,
                    mode=TeaserMode.STANDARD,
                ),
            ],
        )
        await store.save(ctx)

        # First call — should return existing teasers (idempotent)
        result1 = await schema.execute(
            'mutation { generateTeasers(videoId: "v1") { teaserId } }'
        )
        assert result1.errors is None
        ids1 = [t["teaserId"] for t in result1.data["generateTeasers"]]

        # Second call — should return same teaser IDs
        result2 = await schema.execute(
            'mutation { generateTeasers(videoId: "v1") { teaserId } }'
        )
        assert result2.errors is None
        ids2 = [t["teaserId"] for t in result2.data["generateTeasers"]]

        assert ids1 == ids2
        assert ids1 == ["existing-t1"]
