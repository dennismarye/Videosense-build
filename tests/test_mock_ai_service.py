"""Tests for MockAIService — deterministic AI responses."""

import pytest

from src.context.models import (
    CropRegion,
    DescriptionVariant,
    HookScore,
    Platform,
    Scene,
    SpeechRegion,
    SuggestedClip,
    ThumbnailCandidate,
    TitleStyle,
    TitleVariant,
    Topic,
    VideoContext,
)
from src.local.mock_ai_service import MockAIService


class TestAnalyzeHook:
    async def test_returns_hook_score(self, mock_ai):
        result = await mock_ai.analyze_hook(
            video_path="/tmp/v.mp4", duration=30.0,
            scenes=[Scene(start=2.0, end=10.0)],
            speech_regions=[SpeechRegion(start=1.0, end=5.0)],
            audio_energy=0.7,
        )
        assert isinstance(result, HookScore)
        assert 0.0 <= result.score <= 1.0
        assert result.analysis is not None

    async def test_early_scene_boosts_score(self, mock_ai):
        with_scene = await mock_ai.analyze_hook(
            "/tmp/v.mp4", 30.0,
            scenes=[Scene(start=2.0, end=10.0)],
            speech_regions=[], audio_energy=0.0,
        )
        without_scene = await mock_ai.analyze_hook(
            "/tmp/v.mp4", 30.0,
            scenes=[Scene(start=10.0, end=20.0)],
            speech_regions=[], audio_energy=0.0,
        )
        assert with_scene.score > without_scene.score

    async def test_early_speech_boosts_score(self, mock_ai):
        with_speech = await mock_ai.analyze_hook(
            "/tmp/v.mp4", 30.0, scenes=[],
            speech_regions=[SpeechRegion(start=1.0, end=5.0)],
            audio_energy=0.0,
        )
        without_speech = await mock_ai.analyze_hook(
            "/tmp/v.mp4", 30.0, scenes=[],
            speech_regions=[SpeechRegion(start=5.0, end=10.0)],
            audio_energy=0.0,
        )
        assert with_speech.score > without_speech.score

    async def test_high_audio_energy_boosts_score(self, mock_ai):
        high = await mock_ai.analyze_hook(
            "/tmp/v.mp4", 30.0, scenes=[], speech_regions=[], audio_energy=0.8,
        )
        low = await mock_ai.analyze_hook(
            "/tmp/v.mp4", 30.0, scenes=[], speech_regions=[], audio_energy=0.3,
        )
        assert high.score > low.score

    async def test_all_signals_present_caps_at_1(self, mock_ai):
        result = await mock_ai.analyze_hook(
            "/tmp/v.mp4", 30.0,
            scenes=[Scene(start=1.0, end=5.0)],
            speech_regions=[SpeechRegion(start=0.5, end=3.0)],
            audio_energy=0.9,
        )
        assert result.score <= 1.0

    async def test_no_signals_weak_hook(self, mock_ai):
        result = await mock_ai.analyze_hook(
            "/tmp/v.mp4", 5.0, scenes=[], speech_regions=[], audio_energy=0.0,
        )
        assert result.score == 0.0
        assert "Weak hook" in result.analysis


class TestGenerateSummary:
    async def test_with_transcript(self, mock_ai):
        summary = await mock_ai.generate_summary(
            "/tmp/v.mp4",
            transcript="Welcome to this tutorial on Python programming. Today we cover advanced topics.",
            duration=120.0, scene_count=5,
        )
        assert isinstance(summary, str)
        assert len(summary) > 10
        assert "5 distinct scenes" in summary

    async def test_without_transcript(self, mock_ai):
        summary = await mock_ai.generate_summary(
            "/tmp/v.mp4", transcript=None, duration=45.0, scene_count=3,
        )
        assert "45s" in summary
        assert "3 scenes" in summary
        assert "no detected speech" in summary

    async def test_short_transcript_fallback(self, mock_ai):
        summary = await mock_ai.generate_summary(
            "/tmp/v.mp4", transcript="Hi", duration=10.0, scene_count=1,
        )
        assert "1 scene" in summary

    async def test_duration_formatting(self, mock_ai):
        summary = await mock_ai.generate_summary(
            "/tmp/v.mp4", transcript=None, duration=90.0, scene_count=2,
        )
        assert "1m30s" in summary


class TestRankClips:
    async def test_returns_sorted_clips(self, mock_ai):
        moments = [
            {"start": 0.0, "end": 10.0, "raw_score": 0.5, "has_speech": True, "scene_count": 2, "audio_energy": 0.6},
            {"start": 10.0, "end": 30.0, "raw_score": 0.9, "has_speech": False, "scene_count": 1, "audio_energy": 0.3},
        ]
        clips = await mock_ai.rank_clips(moments, "/tmp/v.mp4", 60.0)
        assert len(clips) == 2
        assert clips[0].score >= clips[1].score

    async def test_clip_rationale_includes_speech(self, mock_ai):
        moments = [{"start": 0.0, "end": 10.0, "raw_score": 0.5, "has_speech": True}]
        clips = await mock_ai.rank_clips(moments, "/tmp/v.mp4", 60.0)
        assert "speech present" in clips[0].rationale

    async def test_empty_moments(self, mock_ai):
        clips = await mock_ai.rank_clips([], "/tmp/v.mp4", 60.0)
        assert clips == []


class TestScoreThumbnails:
    async def test_returns_sorted(self, mock_ai):
        candidates = [
            {"timestamp": 5.0, "score": 0.6, "reasons": ["face"]},
            {"timestamp": 15.0, "score": 0.8, "reasons": ["contrast"]},
        ]
        results = await mock_ai.score_thumbnails(candidates, "/tmp/v.mp4")
        assert len(results) == 2
        assert results[0].score >= results[1].score

    async def test_preserves_frame_path(self, mock_ai):
        candidates = [{"timestamp": 5.0, "score": 0.5, "reasons": [], "frame_path": "/frames/5.jpg"}]
        results = await mock_ai.score_thumbnails(candidates, "/tmp/v.mp4")
        assert results[0].frame_path == "/frames/5.jpg"


class TestExtractTopics:
    async def test_always_returns_base_topic(self, mock_ai):
        topics = await mock_ai.extract_topics(None, "/tmp/v.mp4", 30.0)
        assert len(topics) >= 1
        assert topics[0].label == "video content"

    async def test_long_transcript_adds_topic(self, mock_ai):
        transcript = "A" * 200
        topics = await mock_ai.extract_topics(transcript, "/tmp/v.mp4", 30.0)
        labels = [t.label for t in topics]
        assert "spoken discussion" in labels

    async def test_long_duration_adds_topic(self, mock_ai):
        topics = await mock_ai.extract_topics(None, "/tmp/v.mp4", 200.0)
        labels = [t.label for t in topics]
        assert "long-form content" in labels


class TestExtractEntities:
    async def test_returns_empty(self, mock_ai):
        entities = await mock_ai.extract_entities(None, "/tmp/v.mp4")
        assert entities == []


class TestDetectNarrativeBeats:
    async def test_short_video_has_intro(self, mock_ai):
        beats = await mock_ai.detect_narrative_beats(
            "/tmp/v.mp4", scenes=[], transcript=None, duration=10.0,
        )
        types = [b.type for b in beats]
        assert "intro" in types

    async def test_long_video_with_scenes_has_development(self, mock_ai):
        scenes = [Scene(start=0.0, end=20.0), Scene(start=20.0, end=40.0), Scene(start=40.0, end=60.0)]
        beats = await mock_ai.detect_narrative_beats(
            "/tmp/v.mp4", scenes=scenes, transcript=None, duration=60.0,
        )
        types = [b.type for b in beats]
        assert "development" in types

    async def test_includes_conclusion(self, mock_ai):
        beats = await mock_ai.detect_narrative_beats(
            "/tmp/v.mp4", scenes=[], transcript=None, duration=20.0,
        )
        types = [b.type for b in beats]
        assert "conclusion" in types

    async def test_very_short_video(self, mock_ai):
        beats = await mock_ai.detect_narrative_beats(
            "/tmp/v.mp4", scenes=[], transcript=None, duration=3.0,
        )
        # Too short for any beat
        assert len(beats) == 0


class TestGenerateTeaserTitles:
    async def test_generates_per_platform(self, mock_ai):
        titles = await mock_ai.generate_teaser_titles(
            summary="A cool video about tech",
            topics=[Topic(label="technology", confidence=0.9)],
            platforms=["circo", "tiktok"],
            max_chars_per_platform={"circo": 150, "tiktok": 150},
        )
        assert "circo" in titles
        assert "tiktok" in titles

    async def test_respects_max_chars(self, mock_ai):
        titles = await mock_ai.generate_teaser_titles(
            summary="A very long summary " * 10,
            topics=[],
            platforms=["circo"],
            max_chars_per_platform={"circo": 20},
        )
        assert len(titles["circo"]) <= 20

    async def test_no_summary_fallback(self, mock_ai):
        titles = await mock_ai.generate_teaser_titles(
            summary=None, topics=[], platforms=["circo"],
            max_chars_per_platform={"circo": 100},
        )
        assert titles["circo"] == "Check this out"


class TestGenerateTeaserHashtags:
    async def test_generates_per_platform(self, mock_ai):
        hashtags = await mock_ai.generate_teaser_hashtags(
            topics=[Topic(label="tech", confidence=0.9)],
            platforms=["circo", "tiktok"],
            max_hashtags_per_platform={"circo": 10, "tiktok": 5},
        )
        assert "circo" in hashtags
        assert "tiktok" in hashtags

    async def test_respects_max_hashtags(self, mock_ai):
        hashtags = await mock_ai.generate_teaser_hashtags(
            topics=[Topic(label="a", confidence=0.9), Topic(label="b", confidence=0.8)],
            platforms=["x"],
            max_hashtags_per_platform={"x": 3},
        )
        assert len(hashtags["x"]) <= 3

    async def test_includes_base_tags(self, mock_ai):
        hashtags = await mock_ai.generate_teaser_hashtags(
            topics=[], platforms=["circo"],
            max_hashtags_per_platform={"circo": 10},
        )
        assert "#circo" in hashtags["circo"]


# ── V1.2 Content Packaging methods ──────────────────────────

class TestGenerateTitles:
    async def test_returns_title_variants(self, mock_ai):
        ctx = VideoContext(
            video_id="v1",
            summary="A great tech video.",
            topics=[Topic(label="technology", confidence=0.9)],
        )
        titles = await mock_ai.generate_titles(ctx, [Platform.CIRCO])
        assert len(titles) > 0
        assert all(isinstance(t, TitleVariant) for t in titles)

    async def test_multiple_styles(self, mock_ai):
        ctx = VideoContext(video_id="v1", summary="Test video")
        titles = await mock_ai.generate_titles(ctx, [Platform.CIRCO])
        styles = {t.style for t in titles}
        assert len(styles) >= 2

    async def test_all_titles_within_100_chars(self, mock_ai):
        ctx = VideoContext(video_id="v1", summary="A" * 200)
        titles = await mock_ai.generate_titles(ctx, list(Platform))
        for t in titles:
            assert len(t.text) <= 100

    async def test_no_summary_fallback(self, mock_ai):
        ctx = VideoContext(video_id="v1")
        titles = await mock_ai.generate_titles(ctx, [Platform.CIRCO])
        assert len(titles) > 0
        # Should use "Video content" fallback
        assert any("Video content" in t.text or "Untitled" in t.text for t in titles)

    async def test_confidence_in_range(self, mock_ai):
        ctx = VideoContext(video_id="v1", summary="Test")
        titles = await mock_ai.generate_titles(ctx, [Platform.CIRCO])
        for t in titles:
            assert 0.0 <= t.confidence <= 1.0


class TestGenerateDescriptions:
    async def test_returns_description_variants(self, mock_ai):
        ctx = VideoContext(
            video_id="v1",
            summary="A tech review video.",
            topics=[Topic(label="tech", confidence=0.9)],
        )
        descs = await mock_ai.generate_descriptions(ctx, [Platform.CIRCO])
        assert len(descs) > 0
        assert all(isinstance(d, DescriptionVariant) for d in descs)

    async def test_includes_cta_variant(self, mock_ai):
        ctx = VideoContext(video_id="v1", summary="Test")
        descs = await mock_ai.generate_descriptions(ctx, [Platform.CIRCO])
        cta_descs = [d for d in descs if d.includes_cta]
        assert len(cta_descs) >= 1

    async def test_timestamps_with_speech_regions(self, mock_ai):
        ctx = VideoContext(
            video_id="v1",
            summary="Test",
            speech_regions=[
                SpeechRegion(start=0.0, end=10.0, transcript="Intro"),
                SpeechRegion(start=15.0, end=30.0, transcript="Main"),
                SpeechRegion(start=35.0, end=50.0, transcript="End"),
            ],
        )
        descs = await mock_ai.generate_descriptions(ctx, [Platform.YOUTUBE_SHORTS])
        ts_descs = [d for d in descs if d.includes_timestamps]
        assert len(ts_descs) >= 1

    async def test_respects_platform_limits(self, mock_ai):
        ctx = VideoContext(video_id="v1", summary="X" * 1000)
        descs = await mock_ai.generate_descriptions(ctx, [Platform.X])
        for d in descs:
            assert len(d.text) <= 280


class TestGenerateHashtagsV12:
    async def test_returns_per_platform(self, mock_ai):
        ctx = VideoContext(
            video_id="v1",
            topics=[Topic(label="music", confidence=0.9)],
        )
        result = await mock_ai.generate_hashtags(ctx, [Platform.CIRCO, Platform.TIKTOK])
        assert Platform.CIRCO in result
        assert Platform.TIKTOK in result

    async def test_includes_topic_hashtags(self, mock_ai):
        ctx = VideoContext(
            video_id="v1",
            topics=[Topic(label="gaming", confidence=0.9)],
        )
        result = await mock_ai.generate_hashtags(ctx, [Platform.CIRCO])
        tags = result[Platform.CIRCO]
        assert any("gaming" in t.lower() for t in tags)


class TestScoreThumbnailCrop:
    async def test_returns_score_in_range(self, mock_ai):
        crop = CropRegion(x=0, y=0, width=1920, height=1080, aspect_ratio="16:9")
        score = await mock_ai.score_thumbnail_crop("/frames/5.jpg", crop)
        assert 0.0 <= score <= 1.0

    async def test_full_frame_scores_high(self, mock_ai):
        crop = CropRegion(x=0, y=0, width=1920, height=1080, aspect_ratio="16:9")
        score = await mock_ai.score_thumbnail_crop("", crop)
        assert score > 0.8

    async def test_centered_scores_higher(self, mock_ai):
        corner = CropRegion(
            x=0, y=0, width=480, height=270,
            aspect_ratio="16:9", frame_width=1920, frame_height=1080,
        )
        center = CropRegion(
            x=720, y=405, width=480, height=270,
            aspect_ratio="16:9", frame_width=1920, frame_height=1080,
        )
        corner_score = await mock_ai.score_thumbnail_crop("", corner)
        center_score = await mock_ai.score_thumbnail_crop("", center)
        assert center_score > corner_score
