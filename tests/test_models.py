"""Tests for the Video Sense data model (Pydantic models + enums)."""

import uuid

import pytest
from pydantic import ValidationError

from src.context.models import (
    AudioTone,
    CameraMotion,
    CameraMotionType,
    ClipFeedback,
    ClipFormat,
    ContentFlag,
    ContentVariants,
    CropRegion,
    DescriptionVariant,
    Entity,
    FaceDetection,
    FeedbackAction,
    FramingDetection,
    FramingType,
    HashtagSet,
    HookScore,
    JobRequest,
    JobState,
    JobStatus,
    MonetizationTier,
    MotionPeak,
    MusicRegion,
    NarrativeBeat,
    NormalizedHashtag,
    OverallQuality,
    PacingScore,
    Platform,
    PLATFORM_DESCRIPTION_LIMITS,
    PLATFORM_HASHTAG_LIMITS,
    PlatformBundle,
    PlatformConstraints,
    QualityFlag,
    QualityLevel,
    SafetyResult,
    Scene,
    SeriesContext,
    SpeechRegion,
    SuggestedClip,
    Teaser,
    TeaserMode,
    ThumbnailCandidate,
    ThumbnailCrop,
    TimeRange,
    TitleStyle,
    TitleVariant,
    Topic,
    UploadPreset,
    VideoContext,
)


# ── Enum tests ───────────────────────────────────────────────

class TestEnums:
    def test_job_status_values(self):
        assert JobStatus.QUEUED.value == "queued"
        assert JobStatus.PROCESSING.value == "processing"
        assert JobStatus.COMPLETE.value == "complete"
        assert JobStatus.FAILED.value == "failed"

    def test_content_flag_values(self):
        assert ContentFlag.SAFE.value == "SAFE"
        assert ContentFlag.RESTRICT_18.value == "RESTRICT_18+"
        assert ContentFlag.BLOCK_VIOLATION.value == "BLOCK_VIOLATION"

    def test_quality_level_values(self):
        assert QualityLevel.EXCELLENT.value == "EXCELLENT"
        assert QualityLevel.POOR.value == "POOR"

    def test_clip_format_values(self):
        assert ClipFormat.LANDSCAPE.value == "16:9"
        assert ClipFormat.PORTRAIT.value == "9:16"
        assert ClipFormat.SQUARE.value == "1:1"

    def test_teaser_mode_values(self):
        assert TeaserMode.STANDARD.value == "standard"
        assert TeaserMode.TRAILER.value == "trailer"
        assert TeaserMode.HIGHLIGHT_REEL.value == "highlight_reel"

    def test_platform_values(self):
        assert Platform.CIRCO.value == "circo"
        assert Platform.TIKTOK.value == "tiktok"
        assert Platform.INSTAGRAM_REELS.value == "instagram_reels"
        assert Platform.X.value == "x"
        assert Platform.YOUTUBE_SHORTS.value == "youtube_shorts"

    def test_monetization_tier_values(self):
        assert MonetizationTier.FREE.value == "free"
        assert MonetizationTier.PLUS.value == "plus"
        assert MonetizationTier.PRO.value == "pro"
        assert MonetizationTier.ENTERPRISE.value == "enterprise"

    def test_feedback_action_values(self):
        assert FeedbackAction.APPROVED.value == "approved"
        assert FeedbackAction.REJECTED.value == "rejected"

    def test_camera_motion_type_values(self):
        assert CameraMotionType.STATIC.value == "static"
        assert CameraMotionType.PAN.value == "pan"
        assert CameraMotionType.ZOOM.value == "zoom"

    def test_framing_type_values(self):
        assert FramingType.CLOSE_UP.value == "close-up"
        assert FramingType.MEDIUM.value == "medium"
        assert FramingType.WIDE.value == "wide"


# ── Timeline signal tests ────────────────────────────────────

class TestTimelineSignals:
    def test_time_range(self):
        tr = TimeRange(start=1.0, end=5.0)
        assert tr.start == 1.0
        assert tr.end == 5.0

    def test_scene_defaults(self):
        s = Scene(start=0.0, end=10.0)
        assert s.description is None
        assert s.confidence == 0.0

    def test_scene_with_values(self):
        s = Scene(start=0.0, end=10.0, description="Opening", confidence=0.95)
        assert s.description == "Opening"
        assert s.confidence == 0.95

    def test_speech_region_defaults(self):
        sr = SpeechRegion(start=1.0, end=5.0)
        assert sr.transcript is None
        assert sr.keywords == []

    def test_speech_region_with_keywords(self):
        sr = SpeechRegion(start=1.0, end=5.0, transcript="Hello", keywords=["hello"])
        assert sr.transcript == "Hello"
        assert sr.keywords == ["hello"]

    def test_motion_peak(self):
        mp = MotionPeak(timestamp=3.5, intensity=0.8)
        assert mp.timestamp == 3.5
        assert mp.intensity == 0.8


# ── Semantic signal tests ────────────────────────────────────

class TestSemanticSignals:
    def test_topic(self):
        t = Topic(label="tech", confidence=0.9, timestamps=[0.0, 10.0])
        assert t.label == "tech"
        assert len(t.timestamps) == 2

    def test_entity(self):
        e = Entity(name="Python", type="brand", timestamps=[5.0])
        assert e.name == "Python"
        assert e.type == "brand"

    def test_narrative_beat(self):
        nb = NarrativeBeat(type="intro", timestamp=0.0, description="Opening")
        assert nb.type == "intro"


# ── Audio signal tests ───────────────────────────────────────

class TestAudioSignals:
    def test_audio_tone_defaults(self):
        at = AudioTone()
        assert at.energy == 0.0
        assert at.sentiment == 0.0
        assert at.clarity == 0.0

    def test_music_region(self):
        mr = MusicRegion(start=10.0, end=30.0, genre="pop", bpm=120.0)
        assert mr.genre == "pop"
        assert mr.bpm == 120.0


# ── Quality signal tests ─────────────────────────────────────

class TestQualitySignals:
    def test_quality_flag(self):
        qf = QualityFlag(type="dark_frame", timestamp=5.0, severity=0.7)
        assert qf.type == "dark_frame"

    def test_overall_quality_defaults(self):
        oq = OverallQuality()
        assert oq.score == 0
        assert oq.level == QualityLevel.POOR
        assert oq.has_audio is False
        assert oq.issues == []


# ── Artifact tests ───────────────────────────────────────────

class TestArtifacts:
    def test_suggested_clip_auto_id(self):
        c1 = SuggestedClip(start=0.0, end=10.0, score=0.8)
        c2 = SuggestedClip(start=0.0, end=10.0, score=0.8)
        assert c1.clip_id != c2.clip_id  # unique UUIDs

    def test_suggested_clip_defaults(self):
        c = SuggestedClip(start=0.0, end=10.0)
        assert c.score == 0.0
        assert c.rationale is None
        assert c.format == ClipFormat.LANDSCAPE

    def test_thumbnail_candidate(self):
        tc = ThumbnailCandidate(timestamp=5.0, score=0.7, reasons=["face"])
        assert tc.reasons == ["face"]
        assert tc.frame_path is None

    def test_hook_score_defaults(self):
        hs = HookScore()
        assert hs.score == 0.0
        assert hs.analysis is None

    def test_pacing_score(self):
        ps = PacingScore(score=0.6, scenes_per_minute=4.0, analysis="Good pacing")
        assert ps.scenes_per_minute == 4.0


# ── Feedback tests ───────────────────────────────────────────

class TestFeedback:
    def test_clip_feedback(self):
        cf = ClipFeedback(clip_id="clip-1", action=FeedbackAction.APPROVED)
        assert cf.action == FeedbackAction.APPROVED
        assert cf.exported_format is None
        assert cf.timestamp is not None


# ── V1.1 Teaser Engine model tests ──────────────────────────

class TestTeaserModels:
    def test_teaser_defaults(self):
        t = Teaser(source_clip_id="clip-1", start=0.0, end=20.0)
        assert t.teaser_score == 0.0
        assert t.mode == TeaserMode.STANDARD
        assert t.rationale is None
        assert t.narrative_alignment is None
        # Auto-generated UUID
        uuid.UUID(t.teaser_id)

    def test_platform_constraints(self):
        pc = PlatformConstraints(
            platform=Platform.TIKTOK,
            max_duration=60.0,
            aspect_ratio=ClipFormat.PORTRAIT,
            max_title_chars=150,
            max_hashtags=5,
        )
        assert pc.encoding_preset == "fast"  # default

    def test_platform_bundle_defaults(self):
        pb = PlatformBundle(
            teaser_id="t-1", platform=Platform.CIRCO,
            title="Test", format=ClipFormat.LANDSCAPE,
        )
        assert pb.exported is False
        assert pb.watermarked is False
        assert pb.hashtags == []
        assert pb.error is None

    def test_series_context_defaults(self):
        sc = SeriesContext(
            series_id="s-1", series_title="My Series", episode_number=1,
        )
        assert sc.total_episodes is None
        assert sc.teaser_mode == TeaserMode.TRAILER


# ── VideoContext tests ───────────────────────────────────────

class TestVideoContext:
    def test_minimal_context(self):
        ctx = VideoContext(video_id="v1")
        assert ctx.video_id == "v1"
        assert ctx.status == JobStatus.QUEUED
        assert ctx.duration == 0.0
        assert ctx.scenes == []
        assert ctx.suggested_clips == []
        assert ctx.teasers == []
        assert ctx.platform_bundles == []
        assert ctx.tier == MonetizationTier.FREE

    def test_auto_generated_fields(self):
        ctx = VideoContext(video_id="v1")
        uuid.UUID(ctx.job_id)  # should be valid UUID
        assert ctx.created_at is not None
        assert ctx.updated_at is not None

    def test_v11_fields(self):
        ctx = VideoContext(
            video_id="v1",
            tier="pro",
            series_context=SeriesContext(
                series_id="s1", series_title="Test", episode_number=1
            ),
        )
        assert ctx.tier == MonetizationTier.PRO
        assert ctx.series_context.series_id == "s1"


# ── JobRequest / JobState tests ──────────────────────────────

class TestJobModels:
    def test_job_request(self):
        jr = JobRequest(
            video_id="v1", source_path="/tmp/video.mp4"
        )
        assert jr.creator_id is None
        assert jr.tier == MonetizationTier.FREE
        assert jr.options == {}

    def test_job_state_defaults(self):
        js = JobState(video_id="v1")
        assert js.status == JobStatus.QUEUED
        assert js.retries == 0
        assert js.max_retries == 3
        assert js.error is None

    def test_job_state_pipeline_progress_has_all_keys(self):
        js = JobState(video_id="v1")
        expected_keys = {
            "metadata", "scenes", "silence", "audio", "frames", "quality",
            "transcript", "quality_flags", "moments", "clips",
            "hook_analysis", "thumbnail_ranking", "summary", "topics",
            "teaser_selection", "platform_packaging", "teaser_export",
            "content_generation", "hashtag_normalization", "thumbnail_crops", "upload_presets",
        }
        assert set(js.pipeline_progress.keys()) == expected_keys
        # All should start as False
        assert all(v is False for v in js.pipeline_progress.values())


# ── Safety tests ─────────────────────────────────────────────

class TestTierCoercion:
    """Tests for tier field_validator on VideoContext and JobRequest."""

    def test_video_context_coerces_string_to_enum(self):
        ctx = VideoContext(video_id="v1", tier="pro")
        assert ctx.tier == MonetizationTier.PRO

    def test_video_context_accepts_enum(self):
        ctx = VideoContext(video_id="v1", tier=MonetizationTier.ENTERPRISE)
        assert ctx.tier == MonetizationTier.ENTERPRISE

    def test_video_context_rejects_invalid_string(self):
        with pytest.raises(ValidationError, match="Invalid tier"):
            VideoContext(video_id="v1", tier="diamond")

    def test_job_request_coerces_string_to_enum(self):
        jr = JobRequest(video_id="v1", source_path="/tmp/v.mp4", tier="plus")
        assert jr.tier == MonetizationTier.PLUS

    def test_job_request_accepts_enum(self):
        jr = JobRequest(video_id="v1", source_path="/tmp/v.mp4", tier=MonetizationTier.PRO)
        assert jr.tier == MonetizationTier.PRO

    def test_job_request_rejects_invalid_string(self):
        with pytest.raises(ValidationError, match="Invalid tier"):
            JobRequest(video_id="v1", source_path="/tmp/v.mp4", tier="gold")


class TestPlatformBundleValidator:
    """Tests for PlatformBundle model_validator."""

    def test_exported_true_without_path_raises(self):
        with pytest.raises(ValidationError, match="exported=True requires"):
            PlatformBundle(
                teaser_id="t1", platform=Platform.CIRCO,
                title="t", format=ClipFormat.LANDSCAPE,
                exported=True, output_path=None,
            )

    def test_exported_true_with_empty_path_raises(self):
        with pytest.raises(ValidationError, match="exported=True requires"):
            PlatformBundle(
                teaser_id="t1", platform=Platform.CIRCO,
                title="t", format=ClipFormat.LANDSCAPE,
                exported=True, output_path="",
            )

    def test_exported_true_with_valid_path_ok(self):
        b = PlatformBundle(
            teaser_id="t1", platform=Platform.CIRCO,
            title="t", format=ClipFormat.LANDSCAPE,
            exported=True, output_path="/exports/t1.mp4",
        )
        assert b.exported is True

    def test_exported_false_without_path_ok(self):
        b = PlatformBundle(
            teaser_id="t1", platform=Platform.CIRCO,
            title="t", format=ClipFormat.LANDSCAPE,
            exported=False,
        )
        assert b.exported is False


class TestTeaserScoreValidator:
    """Tests for Teaser.teaser_score field_validator."""

    def test_score_above_1_raises(self):
        with pytest.raises(ValidationError, match="teaser_score must be"):
            Teaser(source_clip_id="c1", start=0.0, end=10.0, teaser_score=1.5)

    def test_score_below_0_raises(self):
        with pytest.raises(ValidationError, match="teaser_score must be"):
            Teaser(source_clip_id="c1", start=0.0, end=10.0, teaser_score=-0.1)

    def test_score_at_0_ok(self):
        t = Teaser(source_clip_id="c1", start=0.0, end=10.0, teaser_score=0.0)
        assert t.teaser_score == 0.0

    def test_score_at_1_ok(self):
        t = Teaser(source_clip_id="c1", start=0.0, end=10.0, teaser_score=1.0)
        assert t.teaser_score == 1.0


class TestSafetyResult:
    def test_defaults(self):
        sr = SafetyResult()
        assert sr.content_flag == ContentFlag.SAFE
        assert sr.reason is None
        assert sr.tags == []


# ── V1.2 Content Packaging model tests ──────────────────────

class TestTitleStyleEnum:
    def test_title_style_values(self):
        assert TitleStyle.HOOK.value == "hook"
        assert TitleStyle.DESCRIPTIVE.value == "descriptive"
        assert TitleStyle.QUESTION.value == "question"
        assert TitleStyle.LISTICLE.value == "listicle"
        assert TitleStyle.EMOTIONAL.value == "emotional"


class TestTitleVariant:
    def test_valid_title(self):
        tv = TitleVariant(text="Great Video", style=TitleStyle.HOOK, platform=Platform.CIRCO, confidence=0.9)
        assert tv.text == "Great Video"
        assert tv.style == TitleStyle.HOOK
        assert tv.confidence == 0.9

    def test_title_at_100_chars(self):
        text = "A" * 100
        tv = TitleVariant(text=text, style=TitleStyle.DESCRIPTIVE, platform=Platform.TIKTOK)
        assert len(tv.text) == 100

    def test_title_exceeds_100_chars_raises(self):
        with pytest.raises(ValidationError, match="<= 100 chars"):
            TitleVariant(text="A" * 101, style=TitleStyle.HOOK, platform=Platform.CIRCO)

    def test_confidence_above_1_raises(self):
        with pytest.raises(ValidationError, match="confidence must be"):
            TitleVariant(text="Hi", style=TitleStyle.HOOK, platform=Platform.CIRCO, confidence=1.5)

    def test_confidence_below_0_raises(self):
        with pytest.raises(ValidationError, match="confidence must be"):
            TitleVariant(text="Hi", style=TitleStyle.HOOK, platform=Platform.CIRCO, confidence=-0.1)

    def test_confidence_default(self):
        tv = TitleVariant(text="Hi", style=TitleStyle.HOOK, platform=Platform.CIRCO)
        assert tv.confidence == 0.0


class TestDescriptionVariant:
    def test_valid_description(self):
        dv = DescriptionVariant(text="A short desc", platform=Platform.CIRCO)
        assert dv.includes_cta is False
        assert dv.includes_timestamps is False

    def test_description_with_flags(self):
        dv = DescriptionVariant(
            text="Check it out", platform=Platform.YOUTUBE_SHORTS,
            includes_cta=True, includes_timestamps=True,
        )
        assert dv.includes_cta is True
        assert dv.includes_timestamps is True

    def test_x_description_exceeds_280_raises(self):
        with pytest.raises(ValidationError, match="<= 280 chars"):
            DescriptionVariant(text="A" * 281, platform=Platform.X)

    def test_tiktok_description_at_300_ok(self):
        dv = DescriptionVariant(text="B" * 300, platform=Platform.TIKTOK)
        assert len(dv.text) == 300

    def test_tiktok_description_exceeds_300_raises(self):
        with pytest.raises(ValidationError, match="<= 300 chars"):
            DescriptionVariant(text="B" * 301, platform=Platform.TIKTOK)

    def test_youtube_allows_5000_chars(self):
        dv = DescriptionVariant(text="C" * 5000, platform=Platform.YOUTUBE_SHORTS)
        assert len(dv.text) == 5000


class TestPlatformDescriptionLimits:
    def test_all_platforms_have_limits(self):
        for p in Platform:
            assert p in PLATFORM_DESCRIPTION_LIMITS, f"Missing limit for {p.value}"


class TestContentVariants:
    def test_defaults(self):
        cv = ContentVariants()
        assert cv.titles == []
        assert cv.descriptions == []
        assert cv.generated_at is not None

    def test_with_titles_and_descriptions(self):
        tv = TitleVariant(text="Test", style=TitleStyle.HOOK, platform=Platform.CIRCO)
        dv = DescriptionVariant(text="Desc", platform=Platform.CIRCO)
        cv = ContentVariants(titles=[tv], descriptions=[dv])
        assert len(cv.titles) == 1
        assert len(cv.descriptions) == 1


class TestNormalizedHashtag:
    def test_strips_hash_and_lowercases(self):
        nh = NormalizedHashtag(tag="#TechVideo", relevance=0.8)
        assert nh.tag == "techvideo"

    def test_strips_special_chars(self):
        nh = NormalizedHashtag(tag="#hello-world!", relevance=0.5)
        assert nh.tag == "helloworld"

    def test_preserves_underscores(self):
        nh = NormalizedHashtag(tag="tech_video", relevance=0.7)
        assert nh.tag == "tech_video"

    def test_empty_tag_after_clean_raises(self):
        with pytest.raises(ValidationError, match="at least one alphanumeric"):
            NormalizedHashtag(tag="###")

    def test_relevance_above_1_raises(self):
        with pytest.raises(ValidationError, match="relevance must be"):
            NormalizedHashtag(tag="test", relevance=1.5)

    def test_relevance_below_0_raises(self):
        with pytest.raises(ValidationError, match="relevance must be"):
            NormalizedHashtag(tag="test", relevance=-0.1)

    def test_regional_variant(self):
        nh = NormalizedHashtag(tag="tech", relevance=0.5, regional_variant="#NollywoodTech")
        assert nh.regional_variant == "#NollywoodTech"


class TestHashtagSet:
    def test_empty_set_ok(self):
        hs = HashtagSet(platform=Platform.CIRCO)
        assert hs.hashtags == []
        assert hs.region is None

    def test_within_limit_ok(self):
        tags = [NormalizedHashtag(tag=f"tag{i}", relevance=0.5) for i in range(5)]
        hs = HashtagSet(platform=Platform.TIKTOK, hashtags=tags)
        assert len(hs.hashtags) == 5

    def test_tiktok_exceeds_5_raises(self):
        tags = [NormalizedHashtag(tag=f"tag{i}", relevance=0.5) for i in range(6)]
        with pytest.raises(ValidationError, match="max 5 hashtags"):
            HashtagSet(platform=Platform.TIKTOK, hashtags=tags)

    def test_x_exceeds_3_raises(self):
        tags = [NormalizedHashtag(tag=f"t{i}", relevance=0.5) for i in range(4)]
        with pytest.raises(ValidationError, match="max 3 hashtags"):
            HashtagSet(platform=Platform.X, hashtags=tags)

    def test_instagram_allows_30(self):
        tags = [NormalizedHashtag(tag=f"ig{i}", relevance=0.5) for i in range(30)]
        hs = HashtagSet(platform=Platform.INSTAGRAM_REELS, hashtags=tags)
        assert len(hs.hashtags) == 30

    def test_with_region(self):
        hs = HashtagSet(platform=Platform.CIRCO, region="NG")
        assert hs.region == "NG"


class TestPlatformHashtagLimits:
    def test_all_platforms_have_limits(self):
        for p in Platform:
            assert p in PLATFORM_HASHTAG_LIMITS, f"Missing limit for {p.value}"


class TestCropRegion:
    def test_valid_crop(self):
        cr = CropRegion(x=0, y=0, width=1920, height=1080, aspect_ratio="16:9")
        assert cr.x == 0
        assert cr.frame_width == 1920

    def test_crop_with_custom_frame(self):
        cr = CropRegion(x=100, y=50, width=640, height=360, aspect_ratio="16:9", frame_width=1280, frame_height=720)
        assert cr.frame_width == 1280

    def test_negative_x_raises(self):
        with pytest.raises(ValidationError, match="non-negative"):
            CropRegion(x=-1, y=0, width=100, height=100, aspect_ratio="1:1")

    def test_negative_y_raises(self):
        with pytest.raises(ValidationError, match="non-negative"):
            CropRegion(x=0, y=-1, width=100, height=100, aspect_ratio="1:1")

    def test_zero_width_raises(self):
        with pytest.raises(ValidationError, match="positive"):
            CropRegion(x=0, y=0, width=0, height=100, aspect_ratio="1:1")

    def test_zero_height_raises(self):
        with pytest.raises(ValidationError, match="positive"):
            CropRegion(x=0, y=0, width=100, height=0, aspect_ratio="1:1")

    def test_x_plus_width_exceeds_frame_raises(self):
        with pytest.raises(ValidationError, match="exceeds frame_width"):
            CropRegion(x=1900, y=0, width=100, height=100, aspect_ratio="1:1")

    def test_y_plus_height_exceeds_frame_raises(self):
        with pytest.raises(ValidationError, match="exceeds frame_height"):
            CropRegion(x=0, y=1000, width=100, height=100, aspect_ratio="1:1")

    def test_crop_at_exact_boundary_ok(self):
        cr = CropRegion(x=1820, y=980, width=100, height=100, aspect_ratio="1:1")
        assert cr.x + cr.width == 1920
        assert cr.y + cr.height == 1080


class TestThumbnailCrop:
    def test_valid_thumbnail_crop(self):
        crop = CropRegion(x=0, y=0, width=1920, height=1080, aspect_ratio="16:9")
        tc = ThumbnailCrop(thumbnail_index=0, platform=Platform.CIRCO, crop=crop, score=0.85)
        assert tc.score == 0.85
        assert tc.preview_path is None

    def test_score_above_1_raises(self):
        crop = CropRegion(x=0, y=0, width=1920, height=1080, aspect_ratio="16:9")
        with pytest.raises(ValidationError, match="score must be"):
            ThumbnailCrop(thumbnail_index=0, platform=Platform.CIRCO, crop=crop, score=1.5)


class TestUploadPreset:
    def test_defaults(self):
        up = UploadPreset(platform=Platform.CIRCO)
        assert up.format == "mp4"
        assert up.aspect_ratio == "16:9"
        assert up.max_duration == 60.0
        assert up.title is None
        assert up.description is None
        assert up.hashtags is None
        assert up.thumbnail is None
        assert up.export_path is None
        uuid.UUID(up.preset_id)  # should be valid UUID

    def test_missing_when_empty(self):
        up = UploadPreset(platform=Platform.CIRCO)
        assert set(up.missing) == {"title", "description", "hashtags", "export_path"}
        assert up.ready is False

    def test_ready_when_all_populated(self):
        tv = TitleVariant(text="Test", style=TitleStyle.HOOK, platform=Platform.CIRCO)
        dv = DescriptionVariant(text="Desc", platform=Platform.CIRCO)
        hs = HashtagSet(platform=Platform.CIRCO, hashtags=[NormalizedHashtag(tag="test", relevance=0.5)])
        up = UploadPreset(
            platform=Platform.CIRCO,
            title=tv, description=dv, hashtags=hs,
            export_path="/exports/video.mp4",
        )
        assert up.missing == []
        assert up.ready is True

    def test_partially_filled_not_ready(self):
        tv = TitleVariant(text="Test", style=TitleStyle.HOOK, platform=Platform.CIRCO)
        up = UploadPreset(platform=Platform.CIRCO, title=tv)
        assert "description" in up.missing
        assert "hashtags" in up.missing
        assert "export_path" in up.missing
        assert up.ready is False

    def test_teaser_and_clip_ids(self):
        up = UploadPreset(platform=Platform.TIKTOK, teaser_id="t-1", clip_id="c-1")
        assert up.teaser_id == "t-1"
        assert up.clip_id == "c-1"


class TestVideoContextV12Fields:
    def test_v12_defaults(self):
        ctx = VideoContext(video_id="v1")
        assert ctx.content_variants is None
        assert ctx.thumbnail_crops == []
        assert ctx.upload_presets == []

    def test_v12_with_content_variants(self):
        tv = TitleVariant(text="Title", style=TitleStyle.HOOK, platform=Platform.CIRCO)
        cv = ContentVariants(titles=[tv])
        ctx = VideoContext(video_id="v1", content_variants=cv)
        assert ctx.content_variants is not None
        assert len(ctx.content_variants.titles) == 1

    def test_v12_with_upload_preset(self):
        up = UploadPreset(platform=Platform.TIKTOK)
        ctx = VideoContext(video_id="v1", upload_presets=[up])
        assert len(ctx.upload_presets) == 1
        assert ctx.upload_presets[0].platform == Platform.TIKTOK

    def test_v12_pipeline_progress_keys(self):
        js = JobState(video_id="v1")
        v12_keys = {"content_generation", "hashtag_normalization", "thumbnail_crops", "upload_presets"}
        assert v12_keys.issubset(set(js.pipeline_progress.keys()))
