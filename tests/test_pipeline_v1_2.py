"""Tests for the V1.2 content packaging pipeline."""

import pytest

from src.context.models import (
    ClipFormat,
    JobStatus,
    MonetizationTier,
    Platform,
    PlatformBundle,
    SpeechRegion,
    SuggestedClip,
    Teaser,
    TeaserMode,
    ThumbnailCandidate,
    Topic,
    VideoContext,
)
from src.jobs.pipeline_v1_2 import create_v1_2_pipeline, run_v1_2_pipeline
from src.local.mock_ai_service import MockAIService


# ── Helpers ──────────────────────────────────────────────────

def _make_v11_context() -> VideoContext:
    """
    A VideoContext that looks like V1.1 output:
    has suggested clips, teasers, platform bundles, topics,
    thumbnail candidates, and a summary.
    """
    return VideoContext(
        video_id="v-pipeline-test",
        source_path="/tmp/test.mp4",
        duration=120.0,
        tier=MonetizationTier.PRO,
        summary="A 2-minute tech tutorial covering Python and automation.",
        topics=[
            Topic(label="technology", confidence=0.9, timestamps=[0.0]),
            Topic(label="python", confidence=0.8, timestamps=[30.0]),
        ],
        speech_regions=[
            SpeechRegion(start=0.0, end=10.0, transcript="Welcome everyone"),
            SpeechRegion(start=15.0, end=40.0, transcript="Today we build something"),
            SpeechRegion(start=45.0, end=80.0, transcript="Here is the main code"),
            SpeechRegion(start=85.0, end=115.0, transcript="Thanks for watching"),
        ],
        thumbnail_candidates=[
            ThumbnailCandidate(timestamp=5.0, score=0.9, reasons=["face"]),
            ThumbnailCandidate(timestamp=30.0, score=0.7, reasons=["contrast"]),
        ],
        suggested_clips=[
            SuggestedClip(clip_id="c-1", start=0.0, end=30.0, score=0.8),
        ],
        teasers=[
            Teaser(
                source_clip_id="c-1", start=0.0, end=30.0,
                teaser_score=0.75, mode=TeaserMode.STANDARD,
            ),
        ],
        platform_bundles=[
            PlatformBundle(
                teaser_id="t-1", platform=Platform.CIRCO,
                title="Test", format=ClipFormat.LANDSCAPE,
            ),
            PlatformBundle(
                teaser_id="t-1", platform=Platform.TIKTOK,
                title="Test TT", format=ClipFormat.PORTRAIT,
            ),
        ],
    )


def _make_failed_context() -> VideoContext:
    """A VideoContext that looks like V1 failed."""
    ctx = VideoContext(video_id="v-failed", source_path="/tmp/fail.mp4")
    ctx.status = JobStatus.FAILED
    return ctx


# ── Factory tests ────────────────────────────────────────────

class TestCreateV12Pipeline:
    def test_returns_callable(self):
        ai = MockAIService()
        fn = create_v1_2_pipeline(ai)
        assert callable(fn)


# ── Pipeline execution tests ─────────────────────────────────

class TestV12PipelineExecution:
    @pytest.mark.asyncio
    async def test_content_variants_populated(self):
        ctx = _make_v11_context()
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        assert result.content_variants is not None
        assert len(result.content_variants.titles) > 0
        assert len(result.content_variants.descriptions) > 0

    @pytest.mark.asyncio
    async def test_thumbnail_crops_populated(self):
        ctx = _make_v11_context()
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        assert len(result.thumbnail_crops) > 0

    @pytest.mark.asyncio
    async def test_upload_presets_populated(self):
        ctx = _make_v11_context()
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        # Should have presets for each platform bundle
        assert len(result.upload_presets) == len(ctx.platform_bundles)

    @pytest.mark.asyncio
    async def test_upload_presets_have_titles(self):
        ctx = _make_v11_context()
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        for preset in result.upload_presets:
            assert preset.title is not None

    @pytest.mark.asyncio
    async def test_upload_presets_have_descriptions(self):
        ctx = _make_v11_context()
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        for preset in result.upload_presets:
            assert preset.description is not None

    @pytest.mark.asyncio
    async def test_upload_presets_have_hashtags(self):
        ctx = _make_v11_context()
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        for preset in result.upload_presets:
            assert preset.hashtags is not None


# ── Fault tolerance tests ────────────────────────────────────

class TestV12FaultTolerance:
    @pytest.mark.asyncio
    async def test_failed_v11_skips_v12_steps(self):
        ctx = _make_failed_context()
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        assert result.status == JobStatus.FAILED
        assert result.content_variants is None
        assert result.thumbnail_crops == []
        assert result.upload_presets == []

    @pytest.mark.asyncio
    async def test_v11_data_preserved_after_v12_steps(self):
        """V1.2 steps never overwrite V1.1 fields (teasers, bundles, summary, topics)."""
        ctx = _make_v11_context()
        ai = MockAIService()
        # Snapshot V1.1 field lengths before V1.2 steps
        teasers_before = list(ctx.teasers)
        bundles_before = list(ctx.platform_bundles)
        summary_before = ctx.summary
        topics_before = list(ctx.topics)

        # Run only V1.2 steps (simulate post-V1.1 state by calling run_v1_2_pipeline
        # which calls V1.1 first — V0 will fail on missing file, but V1.1 data we
        # pre-populated should be overwritten by the real V0/V1/V1.1 pipeline).
        # Instead, directly test that V1.2 actions don't touch V1.1 fields:
        from src.actions.content_generator import generate_content
        from src.actions.hashtag_normalizer import normalize_hashtags
        from src.actions.thumbnail_cropper import recommend_crops
        from src.actions.upload_preset import build_upload_presets_with_hashtags

        ctx.content_variants = await generate_content(ctx, ai)
        hashtag_sets = await normalize_hashtags(ctx, ai)
        ctx.thumbnail_crops = await recommend_crops(ctx, ai)
        ctx.upload_presets = build_upload_presets_with_hashtags(ctx, hashtag_sets, ctx.thumbnail_crops)

        # V1.1 data untouched
        assert ctx.teasers == teasers_before
        assert ctx.platform_bundles == bundles_before
        assert ctx.summary == summary_before
        assert ctx.topics == topics_before

    @pytest.mark.asyncio
    async def test_no_ai_service_still_completes(self):
        """Pipeline completes even with ai_service=None (all V1.2 actions handle it)."""
        ctx = _make_v11_context()
        result = await run_v1_2_pipeline(ctx, ai_service=None)
        # Should not crash — actions handle None gracefully
        # Content variants may be empty but context is returned
        assert result.video_id == "v-pipeline-test"

    @pytest.mark.asyncio
    async def test_no_bundles_means_no_presets(self):
        ctx = _make_v11_context()
        ctx.platform_bundles = []
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        assert result.upload_presets == []
        # But content variants and crops should still be generated
        assert result.content_variants is not None
        assert len(result.thumbnail_crops) > 0

    @pytest.mark.asyncio
    async def test_no_thumbnails_means_no_crops(self):
        ctx = _make_v11_context()
        ctx.thumbnail_candidates = []
        ai = MockAIService()
        result = await run_v1_2_pipeline(ctx, ai)
        assert result.thumbnail_crops == []
        # But other V1.2 steps should still run
        assert result.content_variants is not None
