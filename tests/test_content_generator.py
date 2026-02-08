"""Tests for the content generator action module."""

import pytest

from src.actions.content_generator import generate_content
from src.context.models import (
    ContentVariants,
    DescriptionVariant,
    Platform,
    PLATFORM_DESCRIPTION_LIMITS,
    SpeechRegion,
    TitleStyle,
    TitleVariant,
    Topic,
    VideoContext,
)
from src.local.mock_ai_service import MockAIService


@pytest.fixture
def ai_service():
    return MockAIService()


@pytest.fixture
def rich_context():
    """A VideoContext with summary, topics, and speech regions."""
    return VideoContext(
        video_id="v-content-1",
        summary="A deep dive into creative monetization strategies for independent creators.",
        topics=[
            Topic(label="monetization", confidence=0.9, timestamps=[0.0]),
            Topic(label="creator economy", confidence=0.8, timestamps=[10.0]),
        ],
        speech_regions=[
            SpeechRegion(start=0.0, end=10.0, transcript="Welcome to the show"),
            SpeechRegion(start=15.0, end=30.0, transcript="Let's talk about money"),
            SpeechRegion(start=35.0, end=50.0, transcript="Revenue streams matter"),
            SpeechRegion(start=55.0, end=70.0, transcript="Building your audience"),
        ],
        duration=120.0,
    )


@pytest.fixture
def minimal_context():
    """A VideoContext with no summary or topics."""
    return VideoContext(video_id="v-minimal")


class TestGenerateContent:
    @pytest.mark.asyncio
    async def test_returns_content_variants(self, rich_context, ai_service):
        result = await generate_content(rich_context, ai_service)
        assert isinstance(result, ContentVariants)
        assert result.generated_at is not None

    @pytest.mark.asyncio
    async def test_generates_titles_for_all_platforms(self, rich_context, ai_service):
        result = await generate_content(rich_context, ai_service)
        assert len(result.titles) > 0
        platforms_covered = {tv.platform for tv in result.titles}
        assert platforms_covered == set(Platform)

    @pytest.mark.asyncio
    async def test_generates_descriptions_for_all_platforms(self, rich_context, ai_service):
        result = await generate_content(rich_context, ai_service)
        assert len(result.descriptions) > 0
        platforms_covered = {dv.platform for dv in result.descriptions}
        assert platforms_covered == set(Platform)

    @pytest.mark.asyncio
    async def test_titles_within_100_chars(self, rich_context, ai_service):
        result = await generate_content(rich_context, ai_service)
        for tv in result.titles:
            assert len(tv.text) <= 100, f"Title too long: {tv.text!r}"

    @pytest.mark.asyncio
    async def test_descriptions_within_platform_limits(self, rich_context, ai_service):
        result = await generate_content(rich_context, ai_service)
        for dv in result.descriptions:
            limit = PLATFORM_DESCRIPTION_LIMITS.get(dv.platform, 5000)
            assert len(dv.text) <= limit, (
                f"Description for {dv.platform.value} too long: {len(dv.text)} > {limit}"
            )

    @pytest.mark.asyncio
    async def test_specific_platforms(self, rich_context, ai_service):
        result = await generate_content(
            rich_context, ai_service, platforms=[Platform.TIKTOK, Platform.CIRCO]
        )
        platforms_in_titles = {tv.platform for tv in result.titles}
        assert platforms_in_titles == {Platform.TIKTOK, Platform.CIRCO}

    @pytest.mark.asyncio
    async def test_no_ai_service_returns_empty(self, rich_context):
        result = await generate_content(rich_context, ai_service=None)
        assert result.titles == []
        assert result.descriptions == []

    @pytest.mark.asyncio
    async def test_minimal_context(self, minimal_context, ai_service):
        result = await generate_content(minimal_context, ai_service)
        # Should still produce titles (falling back to generic text)
        assert isinstance(result, ContentVariants)
        assert len(result.titles) > 0


class TestTitleStyles:
    @pytest.mark.asyncio
    async def test_multiple_styles_per_platform(self, rich_context, ai_service):
        result = await generate_content(
            rich_context, ai_service, platforms=[Platform.CIRCO]
        )
        styles = {tv.style for tv in result.titles if tv.platform == Platform.CIRCO}
        assert len(styles) >= 2, f"Expected multiple styles, got {styles}"

    @pytest.mark.asyncio
    async def test_confidence_decreases_with_style(self, rich_context, ai_service):
        result = await generate_content(
            rich_context, ai_service, platforms=[Platform.CIRCO]
        )
        circo_titles = [tv for tv in result.titles if tv.platform == Platform.CIRCO]
        # First title should have higher or equal confidence than last
        assert circo_titles[0].confidence >= circo_titles[-1].confidence


class TestDescriptionVariants:
    @pytest.mark.asyncio
    async def test_includes_cta_variant(self, rich_context, ai_service):
        result = await generate_content(
            rich_context, ai_service, platforms=[Platform.CIRCO]
        )
        cta_variants = [dv for dv in result.descriptions if dv.includes_cta]
        assert len(cta_variants) > 0

    @pytest.mark.asyncio
    async def test_includes_timestamps_when_speech_regions(self, rich_context, ai_service):
        result = await generate_content(
            rich_context, ai_service, platforms=[Platform.YOUTUBE_SHORTS]
        )
        ts_variants = [dv for dv in result.descriptions if dv.includes_timestamps]
        # rich_context has 4 speech regions >= 3, so timestamps should be available
        assert len(ts_variants) > 0

    @pytest.mark.asyncio
    async def test_no_timestamps_when_few_speech_regions(self, ai_service):
        ctx = VideoContext(
            video_id="v-few-speech",
            summary="Short video",
            speech_regions=[SpeechRegion(start=0.0, end=5.0)],
        )
        result = await generate_content(ctx, ai_service, platforms=[Platform.CIRCO])
        ts_variants = [dv for dv in result.descriptions if dv.includes_timestamps]
        assert len(ts_variants) == 0
