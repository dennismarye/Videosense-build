"""Tests for the Video Sense CLI (src/cli.py)."""

import json

import pytest
from click.testing import CliRunner

from src.cli import main
from src import __version__


@pytest.fixture
def runner():
    return CliRunner()


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

    def test_health_help(self, runner):
        result = runner.invoke(main, ["health", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output


class TestAnalyzeStub:
    def test_analyze_stub_exits_with_error(self, runner, tmp_path):
        # Create a dummy video file
        video = tmp_path / "test.mp4"
        video.write_bytes(b"\x00" * 100)

        result = runner.invoke(main, ["analyze", str(video)])
        assert result.exit_code == 1
        assert "not yet implemented" in result.output


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
