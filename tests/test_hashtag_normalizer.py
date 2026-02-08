"""Tests for the hashtag normalizer action module."""

import pytest

from src.actions.hashtag_normalizer import (
    normalize_hashtags,
    _normalize_and_dedupe,
)
from src.context.models import (
    HashtagSet,
    NormalizedHashtag,
    Platform,
    PLATFORM_HASHTAG_LIMITS,
    Topic,
    VideoContext,
)
from src.local.mock_ai_service import MockAIService


@pytest.fixture
def ai_service():
    return MockAIService()


@pytest.fixture
def context_with_topics():
    return VideoContext(
        video_id="v-hashtag-1",
        topics=[
            Topic(label="tech review", confidence=0.9, timestamps=[0.0]),
            Topic(label="gadgets", confidence=0.8, timestamps=[10.0]),
            Topic(label="unboxing", confidence=0.7, timestamps=[20.0]),
        ],
    )


@pytest.fixture
def minimal_context():
    return VideoContext(video_id="v-hashtag-min")


class TestNormalizeHashtags:
    @pytest.mark.asyncio
    async def test_returns_hashtag_sets(self, context_with_topics, ai_service):
        result = await normalize_hashtags(context_with_topics, ai_service)
        assert isinstance(result, list)
        assert all(isinstance(hs, HashtagSet) for hs in result)

    @pytest.mark.asyncio
    async def test_one_set_per_platform(self, context_with_topics, ai_service):
        result = await normalize_hashtags(context_with_topics, ai_service)
        platforms = [hs.platform for hs in result]
        assert len(platforms) == len(set(platforms)), "Duplicate platform sets"
        assert set(platforms) == set(Platform)

    @pytest.mark.asyncio
    async def test_specific_platforms(self, context_with_topics, ai_service):
        result = await normalize_hashtags(
            context_with_topics, ai_service,
            platforms=[Platform.TIKTOK, Platform.X],
        )
        assert len(result) == 2
        platforms = {hs.platform for hs in result}
        assert platforms == {Platform.TIKTOK, Platform.X}

    @pytest.mark.asyncio
    async def test_platform_limits_enforced(self, context_with_topics, ai_service):
        result = await normalize_hashtags(context_with_topics, ai_service)
        for hs in result:
            limit = PLATFORM_HASHTAG_LIMITS[hs.platform]
            assert len(hs.hashtags) <= limit, (
                f"{hs.platform.value}: {len(hs.hashtags)} > {limit}"
            )

    @pytest.mark.asyncio
    async def test_tags_are_lowercase(self, context_with_topics, ai_service):
        result = await normalize_hashtags(context_with_topics, ai_service)
        for hs in result:
            for nh in hs.hashtags:
                assert nh.tag == nh.tag.lower(), f"Tag not lowercase: {nh.tag}"

    @pytest.mark.asyncio
    async def test_no_duplicate_tags_per_platform(self, context_with_topics, ai_service):
        result = await normalize_hashtags(context_with_topics, ai_service)
        for hs in result:
            tags = [nh.tag for nh in hs.hashtags]
            assert len(tags) == len(set(tags)), f"Duplicate tags in {hs.platform.value}: {tags}"

    @pytest.mark.asyncio
    async def test_region_propagated(self, context_with_topics, ai_service):
        result = await normalize_hashtags(
            context_with_topics, ai_service,
            platforms=[Platform.CIRCO], region="NG",
        )
        assert result[0].region == "NG"

    @pytest.mark.asyncio
    async def test_no_ai_service(self, context_with_topics):
        result = await normalize_hashtags(context_with_topics, ai_service=None)
        # Should return empty sets per platform
        for hs in result:
            assert len(hs.hashtags) == 0

    @pytest.mark.asyncio
    async def test_minimal_context(self, minimal_context, ai_service):
        result = await normalize_hashtags(
            minimal_context, ai_service, platforms=[Platform.CIRCO]
        )
        assert len(result) == 1
        # Even with no topics, MockAI adds base tags (#circo, #creator, #content)
        assert len(result[0].hashtags) >= 1


class TestNormalizeAndDedupe:
    def test_deduplicates_case_variants(self):
        raw = ["#Tech", "#tech", "#TECH"]
        result = _normalize_and_dedupe(raw, limit=10)
        assert len(result) == 1
        assert result[0].tag == "tech"

    def test_strips_special_chars(self):
        raw = ["#hello-world!", "#test_tag"]
        result = _normalize_and_dedupe(raw, limit=10)
        assert result[0].tag == "helloworld"
        assert result[1].tag == "test_tag"

    def test_enforces_limit(self):
        raw = [f"#tag{i}" for i in range(20)]
        result = _normalize_and_dedupe(raw, limit=5)
        assert len(result) == 5

    def test_relevance_decreases_with_position(self):
        raw = ["#first", "#second", "#third"]
        result = _normalize_and_dedupe(raw, limit=10)
        assert result[0].relevance > result[1].relevance
        assert result[1].relevance > result[2].relevance

    def test_platform_rank_sequential(self):
        raw = ["#a", "#b", "#c"]
        result = _normalize_and_dedupe(raw, limit=10)
        ranks = [nh.platform_rank for nh in result]
        assert ranks == [1, 2, 3]

    def test_empty_input(self):
        result = _normalize_and_dedupe([], limit=10)
        assert result == []

    def test_skips_empty_tags(self):
        raw = ["###", "#valid", "!!!"]
        result = _normalize_and_dedupe(raw, limit=10)
        assert len(result) == 1
        assert result[0].tag == "valid"

    def test_relevance_never_below_minimum(self):
        raw = [f"#tag{i}" for i in range(15)]
        result = _normalize_and_dedupe(raw, limit=15)
        for nh in result:
            assert nh.relevance >= 0.1
