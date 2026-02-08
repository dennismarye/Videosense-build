"""
AI Service Protocol — abstract interface for AI-powered analysis.

Implementations:
- MockAIService (src/local/mock_ai_service.py) — deterministic, no credentials
- GeminiAIService (future) — real Gemini 2.5 Flash inference

All V1 AI-dependent features go through this interface so the
implementation can be swapped via LOCAL_MODE / AI_SERVICE_TYPE.
"""

from typing import List, Optional, Protocol

from src.context.models import (
    CropRegion,
    DescriptionVariant,
    Entity,
    HookScore,
    NarrativeBeat,
    Platform,
    QualityFlag,
    SuggestedClip,
    ThumbnailCandidate,
    TitleVariant,
    Topic,
    VideoContext,
)


class AIService(Protocol):
    """Interface for all AI-powered Video Sense operations."""

    async def analyze_hook(
        self, video_path: str, duration: float, scenes: list, speech_regions: list, audio_energy: float,
    ) -> HookScore:
        """Analyze first 3-5 seconds for attention potential."""
        ...

    async def generate_summary(
        self, video_path: str, transcript: Optional[str], duration: float, scene_count: int,
    ) -> str:
        """Generate 1-2 sentence video summary."""
        ...

    async def rank_clips(
        self, moments: List[dict], video_path: str, duration: float,
    ) -> List[SuggestedClip]:
        """Re-rank candidate moments with AI scoring."""
        ...

    async def score_thumbnails(
        self, candidates: List[dict], video_path: str,
    ) -> List[ThumbnailCandidate]:
        """Re-score thumbnail candidates with AI analysis."""
        ...

    async def extract_topics(
        self, transcript: Optional[str], video_path: str, duration: float,
    ) -> List[Topic]:
        """Extract topics/themes from content."""
        ...

    async def extract_entities(
        self, transcript: Optional[str], video_path: str,
    ) -> List[Entity]:
        """Extract named entities (people, places, brands)."""
        ...

    async def detect_narrative_beats(
        self, video_path: str, scenes: list, transcript: Optional[str], duration: float,
    ) -> List[NarrativeBeat]:
        """Detect narrative structure (intro, climax, conclusion)."""
        ...

    # V1.1: Teaser Engine

    async def generate_teaser_titles(
        self, summary: Optional[str], topics: list, platforms: List[str],
        max_chars_per_platform: dict,
    ) -> dict:
        """Generate platform-specific titles for teasers. Returns {platform: title}."""
        ...

    async def generate_teaser_hashtags(
        self, topics: list, platforms: List[str],
        max_hashtags_per_platform: dict,
    ) -> dict:
        """Generate platform-specific hashtags. Returns {platform: [hashtags]}."""
        ...

    # V1.2: Content Packaging

    async def generate_titles(
        self, context: "VideoContext", platforms: List["Platform"],
    ) -> List["TitleVariant"]:
        """Generate title variants across platforms and styles."""
        ...

    async def generate_descriptions(
        self, context: "VideoContext", platforms: List["Platform"],
    ) -> List["DescriptionVariant"]:
        """Generate description variants per platform."""
        ...

    async def generate_hashtags(
        self, context: "VideoContext", platforms: List["Platform"],
    ) -> dict:
        """Generate raw hashtags per platform. Returns {Platform: [str]}."""
        ...

    async def score_thumbnail_crop(
        self, frame_path: str, crop: "CropRegion",
    ) -> float:
        """Score a thumbnail crop region (0.0-1.0)."""
        ...
