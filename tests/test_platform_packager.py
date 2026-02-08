"""Tests for the platform packager — tier gating, constraints, bundle creation."""

import pytest

from src.actions.platform_packager import (
    PLATFORM_CONSTRAINTS,
    TIER_PLATFORM_ACCESS,
    _get_allowed_platforms,
    _should_watermark,
    package_for_platforms,
)
from src.context.models import (
    ClipFormat,
    MonetizationTier,
    Platform,
    PlatformBundle,
    Teaser,
    TeaserMode,
    Topic,
    VideoContext,
)


def _make_teaser(teaser_id="t1", start=0.0, end=20.0, score=0.8):
    return Teaser(
        teaser_id=teaser_id, source_clip_id="c1",
        start=start, end=end, teaser_score=score,
        mode=TeaserMode.STANDARD,
    )


def _make_context():
    return VideoContext(
        video_id="test",
        duration=120.0,
        summary="A test video about technology",
        topics=[Topic(label="tech", confidence=0.9)],
    )


# ── Tier gating ──────────────────────────────────────────────

class TestTierGating:
    def test_free_tier_circo_only(self):
        platforms = _get_allowed_platforms(MonetizationTier.FREE)
        assert platforms == [Platform.CIRCO]

    def test_plus_tier_circo_only(self):
        platforms = _get_allowed_platforms(MonetizationTier.PLUS)
        assert platforms == [Platform.CIRCO]

    def test_pro_tier_all_platforms(self):
        platforms = _get_allowed_platforms(MonetizationTier.PRO)
        assert len(platforms) == 5
        assert Platform.CIRCO in platforms
        assert Platform.TIKTOK in platforms
        assert Platform.INSTAGRAM_REELS in platforms
        assert Platform.X in platforms
        assert Platform.YOUTUBE_SHORTS in platforms

    def test_enterprise_tier_all_platforms(self):
        platforms = _get_allowed_platforms(MonetizationTier.ENTERPRISE)
        assert len(platforms) == 5


class TestWatermark:
    def test_free_is_watermarked(self):
        assert _should_watermark(MonetizationTier.FREE) is True

    def test_plus_not_watermarked(self):
        assert _should_watermark(MonetizationTier.PLUS) is False

    def test_pro_not_watermarked(self):
        assert _should_watermark(MonetizationTier.PRO) is False

    def test_enterprise_not_watermarked(self):
        assert _should_watermark(MonetizationTier.ENTERPRISE) is False


# ── Platform constraints ─────────────────────────────────────

class TestPlatformConstraints:
    def test_all_platforms_have_constraints(self):
        for platform in Platform:
            assert platform in PLATFORM_CONSTRAINTS

    def test_tiktok_constraints(self):
        c = PLATFORM_CONSTRAINTS[Platform.TIKTOK]
        assert c.max_duration == 60.0
        assert c.aspect_ratio == ClipFormat.PORTRAIT
        assert c.max_title_chars == 150
        assert c.max_hashtags == 5

    def test_instagram_constraints(self):
        c = PLATFORM_CONSTRAINTS[Platform.INSTAGRAM_REELS]
        assert c.max_duration == 90.0
        assert c.max_hashtags == 30

    def test_x_constraints(self):
        c = PLATFORM_CONSTRAINTS[Platform.X]
        assert c.max_title_chars == 280
        assert c.max_hashtags == 3

    def test_youtube_shorts_constraints(self):
        c = PLATFORM_CONSTRAINTS[Platform.YOUTUBE_SHORTS]
        assert c.max_duration == 60.0
        assert c.aspect_ratio == ClipFormat.PORTRAIT


# ── Package for platforms ────────────────────────────────────

class TestPackageForPlatforms:
    async def test_free_tier_single_bundle(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.FREE)
        assert len(bundles) == 1  # 1 teaser x 1 platform (Circo)
        assert bundles[0].platform == Platform.CIRCO
        assert bundles[0].watermarked is True

    async def test_pro_tier_five_bundles(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.PRO)
        assert len(bundles) == 5  # 1 teaser x 5 platforms
        assert all(b.watermarked is False for b in bundles)

    async def test_multiple_teasers(self, mock_ai):
        teasers = [_make_teaser("t1", 0.0, 20.0), _make_teaser("t2", 30.0, 50.0)]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.PRO)
        assert len(bundles) == 10  # 2 teasers x 5 platforms

    async def test_empty_teasers(self, mock_ai):
        ctx = _make_context()
        bundles = await package_for_platforms([], ctx, mock_ai)
        assert bundles == []

    async def test_bundles_have_correct_format(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.PRO)
        for bundle in bundles:
            expected_format = PLATFORM_CONSTRAINTS[bundle.platform].aspect_ratio
            assert bundle.format == expected_format

    async def test_duration_capped_by_platform(self, mock_ai):
        # Teaser is 120s, TikTok max is 60s
        teasers = [_make_teaser("t1", 0.0, 120.0)]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.PRO)
        tiktok_bundle = next(b for b in bundles if b.platform == Platform.TIKTOK)
        assert tiktok_bundle.duration <= 60.0

    async def test_exported_is_false(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai)
        assert all(b.exported is False for b in bundles)

    async def test_titles_generated(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.FREE)
        # MockAI should generate non-empty title
        assert bundles[0].title != ""

    async def test_hashtags_generated(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.FREE)
        assert len(bundles[0].hashtags) > 0

    async def test_no_ai_service(self):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, None, tier=MonetizationTier.FREE)
        assert len(bundles) == 1
        assert bundles[0].title == ""  # No AI → empty title


# ── Watermark invariant tests ────────────────────────────────

class TestWatermarkInvariants:
    async def test_pro_bundles_never_watermarked(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.PRO)
        assert all(b.watermarked is False for b in bundles)

    async def test_free_bundles_always_watermarked(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.FREE)
        assert all(b.watermarked is True for b in bundles)


# ── Metadata constraint enforcement tests ────────────────────

class _OverlongAIService:
    """AI mock that returns titles and hashtags exceeding platform limits."""

    async def generate_teaser_titles(self, summary, topics, platforms, max_chars_dict):
        return {p: "X" * 500 for p in platforms}

    async def generate_teaser_hashtags(self, topics, platforms, max_hashtags_dict):
        return {p: [f"#tag{i}" for i in range(50)] for p in platforms}


class TestMetadataConstraintEnforcement:
    async def test_overlong_title_truncated(self):
        ai = _OverlongAIService()
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, ai, tier=MonetizationTier.FREE)
        for bundle in bundles:
            max_chars = PLATFORM_CONSTRAINTS[bundle.platform].max_title_chars
            assert len(bundle.title) <= max_chars

    async def test_excess_hashtags_trimmed(self):
        ai = _OverlongAIService()
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, ai, tier=MonetizationTier.FREE)
        for bundle in bundles:
            max_tags = PLATFORM_CONSTRAINTS[bundle.platform].max_hashtags
            assert len(bundle.hashtags) <= max_tags

    async def test_mock_ai_also_respects_constraints(self, mock_ai):
        teasers = [_make_teaser()]
        ctx = _make_context()
        bundles = await package_for_platforms(teasers, ctx, mock_ai, tier=MonetizationTier.PRO)
        for bundle in bundles:
            max_chars = PLATFORM_CONSTRAINTS[bundle.platform].max_title_chars
            max_tags = PLATFORM_CONSTRAINTS[bundle.platform].max_hashtags
            assert len(bundle.title) <= max_chars
            assert len(bundle.hashtags) <= max_tags
