"""Tests for the upload preset builder action module."""

import pytest

from src.actions.upload_preset import (
    build_upload_presets,
    build_upload_presets_with_hashtags,
    _index_titles,
    _index_descriptions,
    _index_crops,
    PLATFORM_FORMATS,
)
from src.context.models import (
    ClipFormat,
    ContentVariants,
    CropRegion,
    DescriptionVariant,
    HashtagSet,
    NormalizedHashtag,
    Platform,
    PlatformBundle,
    ThumbnailCrop,
    TitleStyle,
    TitleVariant,
    UploadPreset,
    VideoContext,
)


@pytest.fixture
def context_with_bundles():
    """VideoContext with platform bundles and content variants."""
    return VideoContext(
        video_id="v-preset-1",
        platform_bundles=[
            PlatformBundle(
                teaser_id="t-1", platform=Platform.CIRCO,
                title="Test", format=ClipFormat.LANDSCAPE,
            ),
            PlatformBundle(
                teaser_id="t-1", platform=Platform.TIKTOK,
                title="Test TikTok", format=ClipFormat.PORTRAIT,
            ),
        ],
        content_variants=ContentVariants(
            titles=[
                TitleVariant(text="Circo Title", style=TitleStyle.HOOK, platform=Platform.CIRCO, confidence=0.9),
                TitleVariant(text="Circo Alt", style=TitleStyle.DESCRIPTIVE, platform=Platform.CIRCO, confidence=0.7),
                TitleVariant(text="TikTok Title", style=TitleStyle.HOOK, platform=Platform.TIKTOK, confidence=0.85),
            ],
            descriptions=[
                DescriptionVariant(text="Circo desc", platform=Platform.CIRCO),
                DescriptionVariant(text="TikTok desc", platform=Platform.TIKTOK),
            ],
        ),
    )


@pytest.fixture
def context_no_bundles():
    return VideoContext(video_id="v-preset-empty")


@pytest.fixture
def context_with_exports():
    """Context with exported bundles."""
    return VideoContext(
        video_id="v-preset-exported",
        platform_bundles=[
            PlatformBundle(
                teaser_id="t-1", platform=Platform.CIRCO,
                title="Test", format=ClipFormat.LANDSCAPE,
                exported=True, output_path="/exports/circo.mp4",
            ),
        ],
        content_variants=ContentVariants(
            titles=[
                TitleVariant(text="Title", style=TitleStyle.HOOK, platform=Platform.CIRCO, confidence=0.9),
            ],
            descriptions=[
                DescriptionVariant(text="Desc", platform=Platform.CIRCO),
            ],
        ),
    )


class TestBuildUploadPresets:
    @pytest.mark.asyncio
    async def test_returns_presets(self, context_with_bundles):
        result = await build_upload_presets(context_with_bundles)
        assert isinstance(result, list)
        assert all(isinstance(up, UploadPreset) for up in result)

    @pytest.mark.asyncio
    async def test_one_preset_per_bundle(self, context_with_bundles):
        result = await build_upload_presets(context_with_bundles)
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_empty_bundles(self, context_no_bundles):
        result = await build_upload_presets(context_no_bundles)
        assert result == []

    @pytest.mark.asyncio
    async def test_selects_best_title(self, context_with_bundles):
        result = await build_upload_presets(context_with_bundles)
        circo_preset = next(p for p in result if p.platform == Platform.CIRCO)
        # Should pick the higher confidence title (0.9 > 0.7)
        assert circo_preset.title is not None
        assert circo_preset.title.text == "Circo Title"
        assert circo_preset.title.confidence == 0.9

    @pytest.mark.asyncio
    async def test_selects_description(self, context_with_bundles):
        result = await build_upload_presets(context_with_bundles)
        circo_preset = next(p for p in result if p.platform == Platform.CIRCO)
        assert circo_preset.description is not None
        assert circo_preset.description.text == "Circo desc"

    @pytest.mark.asyncio
    async def test_format_from_platform_defaults(self, context_with_bundles):
        result = await build_upload_presets(context_with_bundles)
        tiktok_preset = next(p for p in result if p.platform == Platform.TIKTOK)
        assert tiktok_preset.aspect_ratio == "9:16"
        assert tiktok_preset.resolution == "1080x1920"

    @pytest.mark.asyncio
    async def test_teaser_id_propagated(self, context_with_bundles):
        result = await build_upload_presets(context_with_bundles)
        for preset in result:
            assert preset.teaser_id == "t-1"

    @pytest.mark.asyncio
    async def test_not_ready_without_hashtags_and_export(self, context_with_bundles):
        result = await build_upload_presets(context_with_bundles)
        for preset in result:
            assert not preset.ready
            assert "hashtags" in preset.missing
            assert "export_path" in preset.missing

    @pytest.mark.asyncio
    async def test_export_path_from_exported_bundle(self, context_with_exports):
        result = await build_upload_presets(context_with_exports)
        assert result[0].export_path == "/exports/circo.mp4"


class TestBuildUploadPresetsWithHashtags:
    def test_with_all_data(self, context_with_exports):
        hashtag_sets = [
            HashtagSet(
                platform=Platform.CIRCO,
                hashtags=[NormalizedHashtag(tag="circo", relevance=0.9)],
            ),
        ]
        result = build_upload_presets_with_hashtags(
            context_with_exports, hashtag_sets
        )
        assert len(result) == 1
        preset = result[0]
        assert preset.hashtags is not None
        assert preset.title is not None
        assert preset.description is not None
        assert preset.export_path == "/exports/circo.mp4"
        assert preset.ready is True

    def test_with_thumbnail_crops(self, context_with_exports):
        crop = CropRegion(x=0, y=0, width=1920, height=1080, aspect_ratio="16:9")
        crops = [ThumbnailCrop(thumbnail_index=0, platform=Platform.CIRCO, crop=crop, score=0.8)]
        hashtag_sets = [
            HashtagSet(
                platform=Platform.CIRCO,
                hashtags=[NormalizedHashtag(tag="test", relevance=0.5)],
            ),
        ]
        result = build_upload_presets_with_hashtags(
            context_with_exports, hashtag_sets, thumbnail_crops=crops
        )
        assert result[0].thumbnail is not None
        assert result[0].thumbnail.score == 0.8

    def test_empty_bundles(self, context_no_bundles):
        result = build_upload_presets_with_hashtags(context_no_bundles, [])
        assert result == []


class TestIndexTitles:
    def test_selects_highest_confidence(self):
        variants = ContentVariants(titles=[
            TitleVariant(text="Low", style=TitleStyle.HOOK, platform=Platform.CIRCO, confidence=0.3),
            TitleVariant(text="High", style=TitleStyle.HOOK, platform=Platform.CIRCO, confidence=0.9),
        ])
        result = _index_titles(variants)
        assert result[Platform.CIRCO].text == "High"

    def test_empty_variants(self):
        assert _index_titles(None) == {}
        assert _index_titles(ContentVariants()) == {}


class TestIndexDescriptions:
    def test_selects_first_per_platform(self):
        variants = ContentVariants(descriptions=[
            DescriptionVariant(text="First", platform=Platform.CIRCO),
            DescriptionVariant(text="Second", platform=Platform.CIRCO),
        ])
        result = _index_descriptions(variants)
        assert result[Platform.CIRCO].text == "First"


class TestIndexCrops:
    def test_selects_best_score(self):
        crop = CropRegion(x=0, y=0, width=1920, height=1080, aspect_ratio="16:9")
        crops = [
            ThumbnailCrop(thumbnail_index=0, platform=Platform.CIRCO, crop=crop, score=0.5),
            ThumbnailCrop(thumbnail_index=1, platform=Platform.CIRCO, crop=crop, score=0.9),
        ]
        result = _index_crops(crops)
        assert result[Platform.CIRCO].score == 0.9

    def test_empty_crops(self):
        assert _index_crops([]) == {}


class TestPlatformFormats:
    def test_all_platforms_have_formats(self):
        for p in Platform:
            assert p in PLATFORM_FORMATS, f"Missing format for {p.value}"

    def test_format_keys(self):
        for p, fmt in PLATFORM_FORMATS.items():
            assert "aspect_ratio" in fmt
            assert "max_duration" in fmt
            assert "resolution" in fmt
