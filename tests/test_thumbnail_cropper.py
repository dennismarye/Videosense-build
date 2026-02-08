"""Tests for the thumbnail cropper action module."""

import pytest

from src.actions.thumbnail_cropper import (
    recommend_crops,
    _compute_crop,
    _heuristic_score,
    _get_frame_dimensions,
    PLATFORM_ASPECT_RATIOS,
)
from src.context.models import (
    CropRegion,
    OverallQuality,
    Platform,
    ThumbnailCandidate,
    ThumbnailCrop,
    VideoContext,
)
from src.local.mock_ai_service import MockAIService


@pytest.fixture
def ai_service():
    return MockAIService()


@pytest.fixture
def context_with_thumbnails():
    return VideoContext(
        video_id="v-crop-1",
        thumbnail_candidates=[
            ThumbnailCandidate(timestamp=5.0, score=0.9, reasons=["face"], frame_path="/frames/5.jpg"),
            ThumbnailCandidate(timestamp=15.0, score=0.8, reasons=["contrast"], frame_path="/frames/15.jpg"),
            ThumbnailCandidate(timestamp=30.0, score=0.7, reasons=["composition"]),
        ],
        duration=60.0,
    )


@pytest.fixture
def context_no_thumbnails():
    return VideoContext(video_id="v-crop-empty", duration=60.0)


class TestRecommendCrops:
    @pytest.mark.asyncio
    async def test_returns_thumbnail_crops(self, context_with_thumbnails, ai_service):
        result = await recommend_crops(context_with_thumbnails, ai_service)
        assert isinstance(result, list)
        assert all(isinstance(tc, ThumbnailCrop) for tc in result)

    @pytest.mark.asyncio
    async def test_crop_per_thumbnail_per_platform(self, context_with_thumbnails, ai_service):
        platforms = [Platform.CIRCO, Platform.TIKTOK]
        result = await recommend_crops(context_with_thumbnails, ai_service, platforms=platforms)
        # 3 thumbnails × 2 platforms = 6 crops
        assert len(result) == 6

    @pytest.mark.asyncio
    async def test_all_platforms_covered(self, context_with_thumbnails, ai_service):
        result = await recommend_crops(context_with_thumbnails, ai_service)
        platforms = {tc.platform for tc in result}
        assert platforms == set(Platform)

    @pytest.mark.asyncio
    async def test_scores_in_range(self, context_with_thumbnails, ai_service):
        result = await recommend_crops(context_with_thumbnails, ai_service)
        for tc in result:
            assert 0.0 <= tc.score <= 1.0, f"Score out of range: {tc.score}"

    @pytest.mark.asyncio
    async def test_crop_bounds_valid(self, context_with_thumbnails, ai_service):
        result = await recommend_crops(context_with_thumbnails, ai_service)
        for tc in result:
            cr = tc.crop
            assert cr.x >= 0
            assert cr.y >= 0
            assert cr.x + cr.width <= cr.frame_width
            assert cr.y + cr.height <= cr.frame_height

    @pytest.mark.asyncio
    async def test_empty_candidates(self, context_no_thumbnails, ai_service):
        result = await recommend_crops(context_no_thumbnails, ai_service)
        assert result == []

    @pytest.mark.asyncio
    async def test_no_ai_service_uses_heuristic(self, context_with_thumbnails):
        result = await recommend_crops(context_with_thumbnails, ai_service=None)
        assert len(result) > 0
        for tc in result:
            assert 0.0 <= tc.score <= 1.0

    @pytest.mark.asyncio
    async def test_max_5_thumbnails(self, ai_service):
        # Create 10 candidates — should only process first 5
        candidates = [
            ThumbnailCandidate(timestamp=float(i), score=0.5)
            for i in range(10)
        ]
        ctx = VideoContext(video_id="v-many", thumbnail_candidates=candidates)
        result = await recommend_crops(ctx, ai_service, platforms=[Platform.CIRCO])
        assert len(result) == 5  # max 5 thumbnails × 1 platform


class TestComputeCrop:
    def test_landscape_16_9_full_frame(self):
        crop = _compute_crop(1920, 1080, "16:9")
        assert crop.width == 1920
        assert crop.height == 1080
        assert crop.x == 0
        assert crop.y == 0

    def test_portrait_9_16_from_landscape(self):
        crop = _compute_crop(1920, 1080, "9:16")
        # Height-constrained: height=1080, width=1080*9/16=607
        assert crop.height == 1080
        assert crop.width == 607
        # Centered horizontally
        assert crop.x == (1920 - 607) // 2
        assert crop.y == 0

    def test_square_from_landscape(self):
        crop = _compute_crop(1920, 1080, "1:1")
        assert crop.width == 1080
        assert crop.height == 1080
        assert crop.x == (1920 - 1080) // 2
        assert crop.y == 0

    def test_4_5_from_landscape(self):
        crop = _compute_crop(1920, 1080, "4:5")
        # Height-constrained: height=1080, width=1080*4/5=864
        assert crop.height == 1080
        assert crop.width == 864

    def test_bounds_never_exceed_frame(self):
        for ar in ["16:9", "9:16", "1:1", "4:5"]:
            crop = _compute_crop(1280, 720, ar)
            assert crop.x + crop.width <= 1280
            assert crop.y + crop.height <= 720
            assert crop.x >= 0
            assert crop.y >= 0

    def test_crop_from_portrait_frame(self):
        crop = _compute_crop(1080, 1920, "16:9")
        # Width-constrained: width=1080, height=1080*9/16=607
        assert crop.width == 1080
        assert crop.height == 607


class TestHeuristicScore:
    def test_full_frame_landscape_scores_high(self):
        crop = CropRegion(x=0, y=0, width=1920, height=1080, aspect_ratio="16:9")
        score = _heuristic_score(crop)
        assert score > 0.8

    def test_small_centered_crop(self):
        crop = CropRegion(
            x=760, y=340, width=400, height=400,
            aspect_ratio="1:1", frame_width=1920, frame_height=1080,
        )
        score = _heuristic_score(crop)
        assert 0.0 <= score <= 1.0

    def test_corner_crop_scores_lower(self):
        corner = CropRegion(
            x=0, y=0, width=480, height=270,
            aspect_ratio="16:9", frame_width=1920, frame_height=1080,
        )
        center = CropRegion(
            x=720, y=405, width=480, height=270,
            aspect_ratio="16:9", frame_width=1920, frame_height=1080,
        )
        assert _heuristic_score(center) > _heuristic_score(corner)


class TestGetFrameDimensions:
    def test_from_quality_resolution(self):
        ctx = VideoContext(
            video_id="v-dim",
            overall_quality=OverallQuality(resolution="1280x720"),
        )
        w, h = _get_frame_dimensions(ctx)
        assert w == 1280
        assert h == 720

    def test_defaults_when_no_quality(self):
        ctx = VideoContext(video_id="v-dim-none")
        w, h = _get_frame_dimensions(ctx)
        assert w == 1920
        assert h == 1080

    def test_defaults_on_invalid_resolution(self):
        ctx = VideoContext(
            video_id="v-dim-bad",
            overall_quality=OverallQuality(resolution="invalid"),
        )
        w, h = _get_frame_dimensions(ctx)
        assert w == 1920
        assert h == 1080


class TestPlatformAspectRatios:
    def test_all_platforms_have_ratio(self):
        for p in Platform:
            assert p in PLATFORM_ASPECT_RATIOS, f"Missing ratio for {p.value}"
