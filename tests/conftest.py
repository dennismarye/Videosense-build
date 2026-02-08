"""
Shared fixtures for Video Sense test suite.
"""

import pytest
from src.context.models import (
    AudioTone,
    ClipFormat,
    HookScore,
    NarrativeBeat,
    OverallQuality,
    QualityLevel,
    Scene,
    SpeechRegion,
    SuggestedClip,
    Teaser,
    TeaserMode,
    ThumbnailCandidate,
    TimeRange,
    Topic,
    VideoContext,
)
from src.local.mock_ai_service import MockAIService
from src.context.context_store import ContextStore


@pytest.fixture
def mock_ai():
    """MockAIService instance."""
    return MockAIService()


@pytest.fixture
def context_store():
    """Fresh in-memory ContextStore."""
    return ContextStore()


@pytest.fixture
def sample_context():
    """A realistic VideoContext with V0+V1 signals populated."""
    ctx = VideoContext(
        video_id="test-video-001",
        creator_id="creator-42",
        source_path="/tmp/test_video.mp4",
        duration=120.0,
        file_size=50_000_000,
        audio_tone=AudioTone(energy=0.7, sentiment=0.2, clarity=0.8),
        scenes=[
            Scene(start=0.0, end=10.0, confidence=0.9),
            Scene(start=10.0, end=35.0, confidence=0.8),
            Scene(start=35.0, end=60.0, confidence=0.85),
            Scene(start=60.0, end=90.0, confidence=0.75),
            Scene(start=90.0, end=120.0, confidence=0.8),
        ],
        silence_regions=[
            TimeRange(start=8.0, end=12.0),
            TimeRange(start=55.0, end=62.0),
        ],
        speech_regions=[
            SpeechRegion(start=0.5, end=7.5, transcript="Welcome to today's video.", keywords=["welcome", "video"]),
            SpeechRegion(start=12.0, end=34.0, transcript="Let me show you something amazing.", keywords=["show", "amazing"]),
            SpeechRegion(start=62.0, end=88.0, transcript="Here's the main point of the discussion.", keywords=["main", "discussion"]),
            SpeechRegion(start=92.0, end=118.0, transcript="Thanks for watching, see you next time.", keywords=["thanks", "watching"]),
        ],
        topics=[
            Topic(label="technology", confidence=0.9, timestamps=[0.0, 35.0]),
            Topic(label="tutorial", confidence=0.7, timestamps=[12.0]),
        ],
        narrative_beats=[
            NarrativeBeat(type="intro", timestamp=0.0, description="Video opening"),
            NarrativeBeat(type="development", timestamp=60.0, description="Core content"),
            NarrativeBeat(type="conclusion", timestamp=117.0, description="Video closing"),
        ],
        overall_quality=OverallQuality(
            score=75,
            level=QualityLevel.GOOD,
            resolution="1920x1080",
            fps=30.0,
            codec="h264",
            has_audio=True,
        ),
        hook_score=HookScore(score=0.7, analysis="Strong opening with scene change and voice."),
        suggested_clips=[
            SuggestedClip(clip_id="clip-1", start=0.0, end=20.0, score=0.85, rationale="speech + scene change", format=ClipFormat.LANDSCAPE),
            SuggestedClip(clip_id="clip-2", start=10.0, end=35.0, score=0.75, rationale="speech + development", format=ClipFormat.PORTRAIT),
            SuggestedClip(clip_id="clip-3", start=35.0, end=60.0, score=0.65, rationale="visual content", format=ClipFormat.SQUARE),
            SuggestedClip(clip_id="clip-4", start=60.0, end=90.0, score=0.70, rationale="main discussion", format=ClipFormat.LANDSCAPE),
            SuggestedClip(clip_id="clip-5", start=90.0, end=120.0, score=0.55, rationale="closing segment", format=ClipFormat.LANDSCAPE),
        ],
        thumbnail_candidates=[
            ThumbnailCandidate(timestamp=2.0, score=0.8, reasons=["face", "contrast"]),
            ThumbnailCandidate(timestamp=15.0, score=0.6, reasons=["scene_boundary"]),
            ThumbnailCandidate(timestamp=45.0, score=0.7, reasons=["sharpness"]),
        ],
        summary="A 2m0s technology tutorial covering multiple topics.",
    )
    return ctx
