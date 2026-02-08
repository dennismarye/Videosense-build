"""Tests for EDL exporter — CMX 3600, timeline markers, FFmpeg commands."""

import pytest

from src.actions.edl_exporter import (
    _build_video_filter,
    _seconds_to_timecode,
    export_edl,
    export_timeline_markers,
    generate_ffmpeg_extract_cmd,
)
from src.context.models import ClipFormat, SuggestedClip


# ── Timecode tests ───────────────────────────────────────────

class TestSecondsToTimecode:
    def test_zero(self):
        assert _seconds_to_timecode(0.0, 24.0) == "00:00:00:00"

    def test_simple_seconds(self):
        assert _seconds_to_timecode(1.0, 24.0) == "00:00:01:00"

    def test_minutes(self):
        assert _seconds_to_timecode(90.0, 24.0) == "00:01:30:00"

    def test_with_frames(self):
        # 0.5 seconds at 24fps = 12 frames
        assert _seconds_to_timecode(0.5, 24.0) == "00:00:00:12"

    def test_negative_clamps_to_zero(self):
        assert _seconds_to_timecode(-5.0, 24.0) == "00:00:00:00"

    def test_hours(self):
        assert _seconds_to_timecode(3661.0, 24.0) == "01:01:01:00"


# ── CMX 3600 EDL tests ──────────────────────────────────────

class TestExportEdl:
    def test_header(self):
        edl = export_edl([], "test-video")
        assert "TITLE: Video Sense - test-video" in edl
        assert "FCM: NON-DROP FRAME" in edl

    def test_single_clip(self):
        clips = [SuggestedClip(clip_id="c1", start=0.0, end=10.0, score=0.8, format=ClipFormat.LANDSCAPE)]
        edl = export_edl(clips, "v1")
        assert "001" in edl
        assert "CLIP: c1" in edl
        assert "SCORE: 0.80" in edl
        assert "FORMAT: 16:9" in edl

    def test_multiple_clips_sequential_record(self):
        clips = [
            SuggestedClip(clip_id="c1", start=0.0, end=10.0, score=0.8),
            SuggestedClip(clip_id="c2", start=20.0, end=30.0, score=0.6),
        ]
        edl = export_edl(clips, "v1")
        assert "001" in edl
        assert "002" in edl

    def test_skips_zero_duration_clips(self):
        clips = [SuggestedClip(clip_id="c1", start=10.0, end=10.0, score=0.5)]
        edl = export_edl(clips, "v1")
        assert "001" not in edl  # should be skipped

    def test_includes_rationale(self):
        clips = [SuggestedClip(clip_id="c1", start=0.0, end=10.0, rationale="great hook")]
        edl = export_edl(clips, "v1")
        assert "RATIONALE: great hook" in edl

    def test_empty_clips(self):
        edl = export_edl([], "v1")
        assert "TITLE:" in edl  # Just the header


# ── Timeline markers tests ──────────────────────────────────

class TestExportTimelineMarkers:
    def test_returns_list_of_dicts(self):
        clips = [SuggestedClip(clip_id="c1", start=0.0, end=10.0, score=0.8)]
        markers = export_timeline_markers(clips)
        assert len(markers) == 1
        assert markers[0]["id"] == "c1"

    def test_high_score_red(self):
        clips = [SuggestedClip(clip_id="c1", start=0.0, end=10.0, score=0.9)]
        markers = export_timeline_markers(clips)
        assert markers[0]["color"] == "#FF2F2F"

    def test_medium_score_orange(self):
        clips = [SuggestedClip(clip_id="c1", start=0.0, end=10.0, score=0.5)]
        markers = export_timeline_markers(clips)
        assert markers[0]["color"] == "#FF8C00"

    def test_low_score_gray(self):
        clips = [SuggestedClip(clip_id="c1", start=0.0, end=10.0, score=0.3)]
        markers = export_timeline_markers(clips)
        assert markers[0]["color"] == "#9CA3AF"

    def test_marker_fields(self):
        clips = [SuggestedClip(clip_id="c1", start=5.0, end=15.0, score=0.6, rationale="test", format=ClipFormat.PORTRAIT)]
        markers = export_timeline_markers(clips)
        m = markers[0]
        assert m["start"] == 5.0
        assert m["end"] == 15.0
        assert m["label"] == "test"
        assert m["format"] == "9:16"

    def test_empty_clips(self):
        assert export_timeline_markers([]) == []


# ── FFmpeg command tests ─────────────────────────────────────

class TestGenerateFfmpegCmd:
    def test_landscape_cmd(self):
        clip = SuggestedClip(clip_id="c1", start=5.0, end=15.0, format=ClipFormat.LANDSCAPE)
        cmd = generate_ffmpeg_extract_cmd(clip, "/input.mp4", "/output.mp4")
        assert cmd[0] == "ffmpeg"
        assert "-ss" in cmd
        assert "5.0" in cmd
        assert "-t" in cmd
        assert "10.0" in cmd  # duration
        assert "scale=1920:1080" in " ".join(cmd)

    def test_portrait_cmd(self):
        clip = SuggestedClip(clip_id="c1", start=0.0, end=10.0, format=ClipFormat.PORTRAIT)
        cmd = generate_ffmpeg_extract_cmd(clip, "/input.mp4", "/output.mp4")
        assert "crop=ih*9/16:ih,scale=1080:1920" in " ".join(cmd)

    def test_square_cmd(self):
        clip = SuggestedClip(clip_id="c1", start=0.0, end=10.0, format=ClipFormat.SQUARE)
        cmd = generate_ffmpeg_extract_cmd(clip, "/input.mp4", "/output.mp4")
        vf = " ".join(cmd)
        assert "1080:1080" in vf

    def test_overwrite_flag(self):
        clip = SuggestedClip(clip_id="c1", start=0.0, end=10.0)
        cmd = generate_ffmpeg_extract_cmd(clip, "/input.mp4", "/output.mp4")
        assert "-y" in cmd

    def test_output_path_is_last(self):
        clip = SuggestedClip(clip_id="c1", start=0.0, end=10.0)
        cmd = generate_ffmpeg_extract_cmd(clip, "/input.mp4", "/output.mp4")
        assert cmd[-1] == "/output.mp4"


# ── Video filter tests ──────────────────────────────────────

class TestBuildVideoFilter:
    def test_landscape(self):
        assert _build_video_filter(ClipFormat.LANDSCAPE) == "scale=1920:1080"

    def test_portrait(self):
        assert _build_video_filter(ClipFormat.PORTRAIT) == "crop=ih*9/16:ih,scale=1080:1920"

    def test_square(self):
        vf = _build_video_filter(ClipFormat.SQUARE)
        assert "1080:1080" in vf
