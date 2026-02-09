"""Tests for the Video Sense CLI (src/cli.py)."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from src.cli import main
from src import __version__
from src.context.models import (
    ContentVariants,
    CropRegion,
    DescriptionVariant,
    JobStatus,
    MonetizationTier,
    Platform,
    Scene,
    SpeechRegion,
    SuggestedClip,
    ClipFormat,
    Teaser,
    TeaserMode,
    ThumbnailCrop,
    TitleStyle,
    TitleVariant,
    Topic,
    UploadPreset,
    VideoContext,
    HookScore,
    PlatformBundle,
)


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def dummy_video(tmp_path):
    """Create a dummy video file for CLI tests."""
    video = tmp_path / "test.mp4"
    video.write_bytes(b"\x00" * 100)
    return str(video)


def _make_v12_context(video_id="test-id", source_path="/tmp/test.mp4"):
    """Build a realistic V1.2 VideoContext for CLI testing."""
    return VideoContext(
        video_id=video_id,
        source_path=source_path,
        status=JobStatus.COMPLETE,
        duration=120.0,
        scenes=[Scene(start=0.0, end=60.0, confidence=0.9), Scene(start=60.0, end=120.0, confidence=0.8)],
        speech_regions=[SpeechRegion(start=1.0, end=55.0, transcript="Hello")],
        suggested_clips=[SuggestedClip(clip_id="c1", start=0.0, end=30.0, score=0.8, rationale="test", format=ClipFormat.LANDSCAPE)],
        topics=[Topic(label="tech", confidence=0.9, timestamps=[0.0])],
        summary="A test video about technology.",
        hook_score=HookScore(score=0.75, analysis="Good hook"),
        teasers=[Teaser(teaser_id="t1", source_clip_id="c1", start=0.0, end=15.0, teaser_score=0.8, mode=TeaserMode.STANDARD, rationale="test")],
        platform_bundles=[PlatformBundle(bundle_id="b1", teaser_id="t1", platform=Platform.TIKTOK, title="Test", format=ClipFormat.PORTRAIT)],
        content_variants=ContentVariants(
            titles=[TitleVariant(text="Test Title", style=TitleStyle.HOOK, platform=Platform.CIRCO)],
            descriptions=[DescriptionVariant(text="Test desc", platform=Platform.CIRCO)],
        ),
        thumbnail_crops=[ThumbnailCrop(thumbnail_index=0, platform=Platform.TIKTOK, crop=CropRegion(x=0, y=0, width=1080, height=1920, aspect_ratio="9:16", frame_width=1920, frame_height=1920))],
        upload_presets=[UploadPreset(preset_id="p1", platform=Platform.TIKTOK)],
    )


class TestVersionCommand:
    def test_version_output(self, runner):
        result = runner.invoke(main, ["version"])
        assert result.exit_code == 0
        assert __version__ in result.output
        assert "video-sense" in result.output

    def test_version_includes_python(self, runner):
        result = runner.invoke(main, ["version"])
        assert "Python" in result.output


class TestHelpOutput:
    def test_main_help(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "serve" in result.output
        assert "analyze" in result.output
        assert "health" in result.output
        assert "version" in result.output

    def test_serve_help(self, runner):
        result = runner.invoke(main, ["serve", "--help"])
        assert result.exit_code == 0
        assert "--local" in result.output
        assert "--port" in result.output
        assert "--workers" in result.output

    def test_analyze_help(self, runner):
        result = runner.invoke(main, ["analyze", "--help"])
        assert result.exit_code == 0
        assert "--tier" in result.output
        assert "--pipeline" in result.output
        assert "--output" in result.output
        assert "v1.2" in result.output  # default pipeline version

    def test_health_help(self, runner):
        result = runner.invoke(main, ["health", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output


class TestAnalyzeCommand:
    """Tests for the real analyze command (Phase 6)."""

    def test_analyze_v12_prints_json(self, runner, dummy_video):
        """Default pipeline (v1.2) should print JSON with V1.2 fields."""
        mock_ctx = _make_v12_context(source_path=dummy_video)
        with patch("src.jobs.job_manager.JobManager.submit_and_execute", new_callable=AsyncMock, return_value=mock_ctx):
            result = runner.invoke(main, ["analyze", dummy_video])

        assert result.exit_code == 0
        # Find the JSON block in the output (after the header lines)
        lines = result.output.strip().split("\n")
        json_start = next(i for i, l in enumerate(lines) if l.strip().startswith("{"))
        data = json.loads("\n".join(lines[json_start:]))
        assert data["status"] == "complete"
        assert data["pipeline"] == "v1.2"
        assert data["duration"] == 120.0
        assert data["content_variants"]["titles"] == 1
        assert data["thumbnail_crops"] == 1
        assert data["upload_presets"] == 1
        assert data["presets_ready"] == 0

    def test_analyze_v1_omits_v12_fields(self, runner, dummy_video):
        """V1 pipeline should NOT include V1.2-specific fields."""
        mock_ctx = _make_v12_context(source_path=dummy_video)
        with patch("src.jobs.job_manager.JobManager.submit_and_execute", new_callable=AsyncMock, return_value=mock_ctx):
            result = runner.invoke(main, ["analyze", dummy_video, "--pipeline", "v1"])

        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        json_start = next(i for i, l in enumerate(lines) if l.strip().startswith("{"))
        data = json.loads("\n".join(lines[json_start:]))
        assert data["pipeline"] == "v1"
        assert "suggested_clips" in data
        assert "content_variants" not in data
        assert "teasers" not in data

    def test_analyze_v0_minimal_fields(self, runner, dummy_video):
        """V0 pipeline should only have base fields."""
        mock_ctx = _make_v12_context(source_path=dummy_video)
        with patch("src.jobs.job_manager.JobManager.submit_and_execute", new_callable=AsyncMock, return_value=mock_ctx):
            result = runner.invoke(main, ["analyze", dummy_video, "--pipeline", "v0"])

        assert result.exit_code == 0
        lines = result.output.strip().split("\n")
        json_start = next(i for i, l in enumerate(lines) if l.strip().startswith("{"))
        data = json.loads("\n".join(lines[json_start:]))
        assert data["pipeline"] == "v0"
        assert "scenes" in data
        assert "speech_regions" in data
        assert "suggested_clips" not in data
        assert "teasers" not in data
        assert "content_variants" not in data

    def test_analyze_tier_flag(self, runner, dummy_video):
        """--tier should be reflected in the output."""
        mock_ctx = _make_v12_context(source_path=dummy_video)
        with patch("src.jobs.job_manager.JobManager.submit_and_execute", new_callable=AsyncMock, return_value=mock_ctx):
            result = runner.invoke(main, ["analyze", dummy_video, "--tier", "pro"])

        assert result.exit_code == 0
        assert "pro" in result.output

    def test_analyze_output_writes_file(self, runner, dummy_video, tmp_path):
        """--output should write JSON to file."""
        mock_ctx = _make_v12_context(source_path=dummy_video)
        output_file = str(tmp_path / "result.json")

        with patch("src.jobs.job_manager.JobManager.submit_and_execute", new_callable=AsyncMock, return_value=mock_ctx):
            result = runner.invoke(main, ["analyze", dummy_video, "--output", output_file])

        assert result.exit_code == 0
        assert "Result written to" in result.output
        with open(output_file) as f:
            data = json.load(f)
        assert data["status"] == "complete"
        assert data["pipeline"] == "v1.2"

    def test_analyze_failed_status_exits_nonzero(self, runner, dummy_video):
        """Pipeline returning FAILED status should exit with code 1."""
        mock_ctx = _make_v12_context(source_path=dummy_video)
        mock_ctx.status = JobStatus.FAILED
        with patch("src.jobs.job_manager.JobManager.submit_and_execute", new_callable=AsyncMock, return_value=mock_ctx):
            result = runner.invoke(main, ["analyze", dummy_video])

        assert result.exit_code == 1

    def test_analyze_exception_exits_nonzero(self, runner, dummy_video):
        """Pipeline exception should exit with code 1."""
        with patch("src.jobs.job_manager.JobManager.submit_and_execute", new_callable=AsyncMock, side_effect=RuntimeError("boom")):
            result = runner.invoke(main, ["analyze", dummy_video])

        assert result.exit_code == 1
        assert "Pipeline failed" in result.output

    def test_analyze_nonexistent_file(self, runner):
        """Nonexistent video path should fail (Click validates exists=True)."""
        result = runner.invoke(main, ["analyze", "/nonexistent/video.mp4"])
        assert result.exit_code != 0

    def test_analyze_header_shows_metadata(self, runner, dummy_video):
        """Header should display version, pipeline, and tier."""
        mock_ctx = _make_v12_context(source_path=dummy_video)
        with patch("src.jobs.job_manager.JobManager.submit_and_execute", new_callable=AsyncMock, return_value=mock_ctx):
            result = runner.invoke(main, ["analyze", dummy_video, "--pipeline", "v1.1", "--tier", "enterprise"])

        assert result.exit_code == 0
        assert __version__ in result.output
        assert "v1.1" in result.output
        assert "enterprise" in result.output


class TestHealthCommand:
    def test_health_unreachable(self, runner):
        """Health check against a port that isn't running should fail gracefully."""
        result = runner.invoke(main, ["health", "--port", "19999"])
        assert result.exit_code == 1
        assert "not reachable" in result.output

    def test_health_json_unreachable(self, runner):
        result = runner.invoke(main, ["health", "--json", "--port", "19999"])
        assert result.exit_code == 1
        data = json.loads(result.output)
        assert data["status"] == "unreachable"


class TestVersionString:
    def test_version_format(self):
        """Version should be semver-like."""
        parts = __version__.split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)

    def test_version_is_1_2_0(self):
        assert __version__ == "1.2.0"
