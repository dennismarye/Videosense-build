"""
Video Sense Context Graph — Data Model

The Context Graph is the core data structure of Video Sense.
It turns a raw video into structured, queryable creative context
anchored to timestamps.

Two layers:
  1. Signals — deterministic + AI-extracted observations about the video
  2. Artifacts — actionable outputs derived from signals (clips, thumbnails, etc.)
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator, computed_field


# ── Enums ─────────────────────────────────────────────────────

class JobStatus(str, Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"


class ContentFlag(str, Enum):
    SAFE = "SAFE"
    RESTRICT_18 = "RESTRICT_18+"
    BLOCK_VIOLATION = "BLOCK_VIOLATION"


class QualityLevel(str, Enum):
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class CameraMotionType(str, Enum):
    STATIC = "static"
    PAN = "pan"
    ZOOM = "zoom"
    SHAKE = "shake"
    TRACK = "track"


class FramingType(str, Enum):
    CLOSE_UP = "close-up"
    MEDIUM = "medium"
    WIDE = "wide"


class ClipFormat(str, Enum):
    LANDSCAPE = "16:9"
    PORTRAIT = "9:16"
    SQUARE = "1:1"


class FeedbackAction(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class TeaserMode(str, Enum):
    STANDARD = "standard"
    TRAILER = "trailer"
    HIGHLIGHT_REEL = "highlight_reel"


class Platform(str, Enum):
    CIRCO = "circo"
    TIKTOK = "tiktok"
    INSTAGRAM_REELS = "instagram_reels"
    X = "x"
    YOUTUBE_SHORTS = "youtube_shorts"


class MonetizationTier(str, Enum):
    FREE = "free"
    PLUS = "plus"
    PRO = "pro"
    ENTERPRISE = "enterprise"


# ── Timeline Signals ──────────────────────────────────────────

class TimeRange(BaseModel):
    """A span of time within the video."""
    start: float  # seconds
    end: float    # seconds


class Scene(BaseModel):
    """A detected scene boundary with optional description."""
    start: float
    end: float
    description: Optional[str] = None
    confidence: float = 0.0


class MotionPeak(BaseModel):
    """A point of high visual motion."""
    timestamp: float
    intensity: float  # 0.0 - 1.0


class SpeechRegion(BaseModel):
    """A region where speech is detected, with optional transcript."""
    start: float
    end: float
    transcript: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)


# ── Semantic Signals ──────────────────────────────────────────

class Topic(BaseModel):
    """A detected topic/theme in the video."""
    label: str
    confidence: float = 0.0
    timestamps: List[float] = Field(default_factory=list)


class Entity(BaseModel):
    """A detected entity (person, place, brand, etc.)."""
    name: str
    type: str  # person, place, brand, object
    timestamps: List[float] = Field(default_factory=list)


class NarrativeBeat(BaseModel):
    """A narrative moment (intro, climax, conclusion, transition)."""
    type: str
    timestamp: float
    description: Optional[str] = None


# ── Audio Signals ─────────────────────────────────────────────

class AudioTone(BaseModel):
    """Overall audio characteristics."""
    energy: float = 0.0       # 0.0 (quiet) - 1.0 (loud)
    sentiment: float = 0.0    # -1.0 (negative) - 1.0 (positive)
    clarity: float = 0.0      # 0.0 (muddy) - 1.0 (clear)


class MusicRegion(BaseModel):
    """A region where music is detected."""
    start: float
    end: float
    genre: Optional[str] = None
    bpm: Optional[float] = None


# ── Visual Signals ────────────────────────────────────────────

class FaceDetection(BaseModel):
    """A detected face at a point in time."""
    timestamp: float
    bounding_box: Optional[dict] = None  # {x, y, width, height}
    expression: Optional[str] = None


class FramingDetection(BaseModel):
    """Detected framing type at a point in time."""
    timestamp: float
    type: FramingType


class CameraMotion(BaseModel):
    """Detected camera motion over a time range."""
    start: float
    end: float
    type: CameraMotionType


# ── Quality Signals ───────────────────────────────────────────

class QualityFlag(BaseModel):
    """A detected quality issue."""
    type: str       # dark_frame, low_audio, static_intro, shaky, etc.
    timestamp: float
    severity: float = 0.0  # 0.0 (minor) - 1.0 (severe)


class OverallQuality(BaseModel):
    """Aggregate quality assessment."""
    score: int = 0       # 0-100
    level: QualityLevel = QualityLevel.POOR
    resolution: Optional[str] = None
    fps: Optional[float] = None
    codec: Optional[str] = None
    has_audio: bool = False
    issues: List[str] = Field(default_factory=list)


# ── Generated Artifacts ───────────────────────────────────────

class SuggestedClip(BaseModel):
    """A suggested clip extracted from the video."""
    clip_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    start: float
    end: float
    score: float = 0.0       # 0.0 - 1.0
    rationale: Optional[str] = None
    format: ClipFormat = ClipFormat.LANDSCAPE


class ThumbnailCandidate(BaseModel):
    """A candidate thumbnail frame."""
    timestamp: float
    score: float = 0.0       # 0.0 - 1.0
    reasons: List[str] = Field(default_factory=list)
    frame_path: Optional[str] = None  # local/S3 path to extracted frame


class HookScore(BaseModel):
    """Analysis of the first 3-5 seconds."""
    score: float = 0.0       # 0.0 - 1.0
    analysis: Optional[str] = None


class PacingScore(BaseModel):
    """Scene change frequency analysis."""
    score: float = 0.0       # 0.0 - 1.0
    scenes_per_minute: float = 0.0
    analysis: Optional[str] = None


# ── Feedback ──────────────────────────────────────────────────

class ClipFeedback(BaseModel):
    """Creator feedback on a suggested clip."""
    clip_id: str
    action: FeedbackAction
    exported_format: Optional[ClipFormat] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ── V1.1 Teaser Engine ──────────────────────────────────────

class Teaser(BaseModel):
    """A selected teaser clip derived from V1 suggested_clips."""
    teaser_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_clip_id: str
    start: float
    end: float
    teaser_score: float = 0.0
    mode: TeaserMode = TeaserMode.STANDARD
    rationale: Optional[str] = None
    narrative_alignment: Optional[str] = None

    @field_validator("teaser_score")
    @classmethod
    def _validate_teaser_score(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"teaser_score must be between 0.0 and 1.0, got {v}")
        return v


class PlatformConstraints(BaseModel):
    """Platform-specific encoding and content rules."""
    platform: Platform
    max_duration: float
    aspect_ratio: ClipFormat
    max_title_chars: int
    max_hashtags: int
    encoding_preset: str = "fast"


class PlatformBundle(BaseModel):
    """A platform-specific package for a teaser."""
    bundle_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    teaser_id: str
    platform: Platform
    title: str
    hashtags: List[str] = Field(default_factory=list)
    format: ClipFormat
    output_path: Optional[str] = None
    duration: float = 0.0
    exported: bool = False
    error: Optional[str] = None
    watermarked: bool = False

    @model_validator(mode="after")
    def _validate_exported_has_path(self):
        if self.exported and not self.output_path:
            raise ValueError("exported=True requires a non-empty output_path")
        return self


class SeriesContext(BaseModel):
    """Series metadata passed in JobRequest.options."""
    series_id: str
    series_title: str
    episode_number: int
    total_episodes: Optional[int] = None
    teaser_mode: TeaserMode = TeaserMode.TRAILER


# ── Safety Result (from existing pipeline) ────────────────────

class SafetyResult(BaseModel):
    """Result from the existing content safety check."""
    content_flag: ContentFlag = ContentFlag.SAFE
    reason: Optional[str] = None
    tags: List[dict] = Field(default_factory=list)
    ai_context: Optional[str] = None


# ── V1.2 Content Packaging ────────────────────────────────────

class TitleStyle(str, Enum):
    HOOK = "hook"
    DESCRIPTIVE = "descriptive"
    QUESTION = "question"
    LISTICLE = "listicle"
    EMOTIONAL = "emotional"


class TitleVariant(BaseModel):
    """A generated title variant for a specific platform."""
    text: str
    style: TitleStyle
    platform: Platform
    confidence: float = 0.0

    @field_validator("text")
    @classmethod
    def _validate_text_length(cls, v):
        if len(v) > 100:
            raise ValueError(f"Title text must be <= 100 chars, got {len(v)}")
        return v

    @field_validator("confidence")
    @classmethod
    def _validate_confidence(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"confidence must be between 0.0 and 1.0, got {v}")
        return v


# Platform-specific description character limits
PLATFORM_DESCRIPTION_LIMITS: dict[Platform, int] = {
    Platform.YOUTUBE_SHORTS: 5000,
    Platform.INSTAGRAM_REELS: 2200,
    Platform.CIRCO: 2000,
    Platform.TIKTOK: 300,
    Platform.X: 280,
}


class DescriptionVariant(BaseModel):
    """A generated description variant for a specific platform."""
    text: str
    platform: Platform
    includes_cta: bool = False
    includes_timestamps: bool = False

    @model_validator(mode="after")
    def _validate_text_length(self):
        limit = PLATFORM_DESCRIPTION_LIMITS.get(self.platform, 5000)
        if len(self.text) > limit:
            raise ValueError(
                f"Description for {self.platform.value} must be <= {limit} chars, got {len(self.text)}"
            )
        return self


class ContentVariants(BaseModel):
    """Collection of generated title and description variants."""
    titles: List[TitleVariant] = Field(default_factory=list)
    descriptions: List[DescriptionVariant] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class NormalizedHashtag(BaseModel):
    """A normalized, ranked hashtag."""
    tag: str
    relevance: float = 0.0
    platform_rank: int = 0
    regional_variant: Optional[str] = None

    @field_validator("tag")
    @classmethod
    def _normalize_tag(cls, v):
        # Strip leading # if present, lowercase, remove non-alphanumeric (except underscore)
        tag = v.lstrip("#").lower()
        cleaned = "".join(c for c in tag if c.isalnum() or c == "_")
        if not cleaned:
            raise ValueError(f"Tag must contain at least one alphanumeric character, got '{v}'")
        return cleaned

    @field_validator("relevance")
    @classmethod
    def _validate_relevance(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"relevance must be between 0.0 and 1.0, got {v}")
        return v


# Platform hashtag count limits
PLATFORM_HASHTAG_LIMITS: dict[Platform, int] = {
    Platform.TIKTOK: 5,
    Platform.X: 3,
    Platform.CIRCO: 10,
    Platform.INSTAGRAM_REELS: 30,
    Platform.YOUTUBE_SHORTS: 15,
}


class HashtagSet(BaseModel):
    """A set of normalized hashtags for a specific platform."""
    platform: Platform
    hashtags: List[NormalizedHashtag] = Field(default_factory=list)
    region: Optional[str] = None

    @model_validator(mode="after")
    def _enforce_platform_limit(self):
        limit = PLATFORM_HASHTAG_LIMITS.get(self.platform, 10)
        if len(self.hashtags) > limit:
            raise ValueError(
                f"{self.platform.value} allows max {limit} hashtags, got {len(self.hashtags)}"
            )
        return self


class CropRegion(BaseModel):
    """A crop region within a frame, validated against frame bounds."""
    x: int
    y: int
    width: int
    height: int
    aspect_ratio: str  # "16:9", "9:16", "1:1", "4:5"
    frame_width: int = 1920
    frame_height: int = 1080

    @model_validator(mode="after")
    def _validate_bounds(self):
        if self.x < 0 or self.y < 0:
            raise ValueError(f"Crop origin must be non-negative, got x={self.x}, y={self.y}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError(f"Crop dimensions must be positive, got {self.width}x{self.height}")
        if self.x + self.width > self.frame_width:
            raise ValueError(
                f"Crop x({self.x}) + width({self.width}) = {self.x + self.width} exceeds frame_width({self.frame_width})"
            )
        if self.y + self.height > self.frame_height:
            raise ValueError(
                f"Crop y({self.y}) + height({self.height}) = {self.y + self.height} exceeds frame_height({self.frame_height})"
            )
        return self


class ThumbnailCrop(BaseModel):
    """A thumbnail crop recommendation for a specific platform."""
    thumbnail_index: int
    platform: Platform
    crop: CropRegion
    score: float = 0.0
    preview_path: Optional[str] = None

    @field_validator("score")
    @classmethod
    def _validate_score(cls, v):
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"score must be between 0.0 and 1.0, got {v}")
        return v


class UploadPreset(BaseModel):
    """A ready-to-publish preset bundling format + metadata + constraints."""
    preset_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    platform: Platform
    teaser_id: Optional[str] = None
    clip_id: Optional[str] = None

    # Video format
    format: str = "mp4"
    aspect_ratio: str = "16:9"
    max_duration: float = 60.0
    resolution: str = "1920x1080"

    # Metadata
    title: Optional[TitleVariant] = None
    description: Optional[DescriptionVariant] = None
    hashtags: Optional[HashtagSet] = None
    thumbnail: Optional[ThumbnailCrop] = None

    # Export status
    export_path: Optional[str] = None

    @property
    def missing(self) -> List[str]:
        """Returns list of unfilled required fields."""
        missing = []
        if self.title is None:
            missing.append("title")
        if self.description is None:
            missing.append("description")
        if self.hashtags is None:
            missing.append("hashtags")
        if self.export_path is None:
            missing.append("export_path")
        return missing

    @property
    def ready(self) -> bool:
        """True iff all required fields are populated and export exists."""
        return len(self.missing) == 0


# ── The Context Graph ─────────────────────────────────────────

class VideoContext(BaseModel):
    """
    The complete Context Graph for a single video.

    This is the central data structure of Video Sense.
    Every signal, artifact, and feedback item is anchored here.
    """

    # Identity
    video_id: str
    creator_id: Optional[str] = None
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Source metadata
    source_path: Optional[str] = None  # S3 path or local path
    duration: float = 0.0
    file_size: int = 0

    # Safety (from existing pipeline)
    safety: Optional[SafetyResult] = None

    # Timeline signals
    scenes: List[Scene] = Field(default_factory=list)
    motion_peaks: List[MotionPeak] = Field(default_factory=list)
    silence_regions: List[TimeRange] = Field(default_factory=list)
    speech_regions: List[SpeechRegion] = Field(default_factory=list)

    # Semantic signals
    topics: List[Topic] = Field(default_factory=list)
    entities: List[Entity] = Field(default_factory=list)
    narrative_beats: List[NarrativeBeat] = Field(default_factory=list)

    # Audio signals
    audio_tone: Optional[AudioTone] = None
    music_regions: List[MusicRegion] = Field(default_factory=list)
    voice_music_ratio: Optional[float] = None

    # Visual signals
    faces: List[FaceDetection] = Field(default_factory=list)
    framing: List[FramingDetection] = Field(default_factory=list)
    camera_motion: List[CameraMotion] = Field(default_factory=list)

    # Quality signals
    quality_flags: List[QualityFlag] = Field(default_factory=list)
    overall_quality: Optional[OverallQuality] = None

    # Generated artifacts
    suggested_clips: List[SuggestedClip] = Field(default_factory=list)
    thumbnail_candidates: List[ThumbnailCandidate] = Field(default_factory=list)
    summary: Optional[str] = None
    hook_score: Optional[HookScore] = None
    pacing_score: Optional[PacingScore] = None

    # Feedback (populated post-interaction)
    clip_feedback: List[ClipFeedback] = Field(default_factory=list)

    # V1.1: Teaser Engine
    tier: MonetizationTier = MonetizationTier.FREE
    teasers: List[Teaser] = Field(default_factory=list)
    platform_bundles: List[PlatformBundle] = Field(default_factory=list)
    series_context: Optional[SeriesContext] = None

    # V1.2: Content Packaging
    content_variants: Optional[ContentVariants] = None
    thumbnail_crops: List[ThumbnailCrop] = Field(default_factory=list)
    upload_presets: List[UploadPreset] = Field(default_factory=list)

    @field_validator("tier", mode="before")
    @classmethod
    def _coerce_tier(cls, v):
        if isinstance(v, MonetizationTier):
            return v
        if isinstance(v, str) and v in {t.value for t in MonetizationTier}:
            return MonetizationTier(v)
        raise ValueError(
            f"Invalid tier '{v}'. Must be one of: {[t.value for t in MonetizationTier]}"
        )


# ── Job Model ─────────────────────────────────────────────────

class JobRequest(BaseModel):
    """Input contract for triggering Video Sense analysis."""
    video_id: str
    creator_id: Optional[str] = None
    source_path: str
    tier: MonetizationTier = MonetizationTier.FREE
    options: dict = Field(default_factory=dict)

    @field_validator("tier", mode="before")
    @classmethod
    def _coerce_tier(cls, v):
        if isinstance(v, MonetizationTier):
            return v
        if isinstance(v, str) and v in {t.value for t in MonetizationTier}:
            return MonetizationTier(v)
        raise ValueError(
            f"Invalid tier '{v}'. Must be one of: {[t.value for t in MonetizationTier]}"
        )


class JobState(BaseModel):
    """Persistent job state for tracking and idempotency."""
    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    video_id: str
    status: JobStatus = JobStatus.QUEUED
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    retries: int = 0
    max_retries: int = 3

    # Pipeline progress (which signals have been extracted)
    pipeline_progress: dict = Field(default_factory=lambda: {
        # V0
        "metadata": False,
        "scenes": False,
        "silence": False,
        "audio": False,
        "frames": False,
        "quality": False,
        # V1
        "transcript": False,
        "quality_flags": False,
        "moments": False,
        "clips": False,
        "hook_analysis": False,
        "thumbnail_ranking": False,
        "summary": False,
        "topics": False,
        # V1.1
        "teaser_selection": False,
        "platform_packaging": False,
        "teaser_export": False,
        # V1.2
        "content_generation": False,
        "hashtag_normalization": False,
        "thumbnail_crops": False,
        "upload_presets": False,
    })
