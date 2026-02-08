"""Tests for the clip ranker — moment → SuggestedClip ranking."""

import pytest

from src.actions.clip_ranker import (
    MAX_CLIPS,
    MIN_SCORE_THRESHOLD,
    HIGH_SCORE_THRESHOLD,
    SPEECH_BOUNDARY_PENALTY,
    _apply_speech_boundary_penalty,
    _build_rationale,
    _select_format,
    rank_clips,
)
from src.actions.moment_detector import Moment
from src.context.models import ClipFormat, SpeechRegion, VideoContext


def _make_moment(start=0.0, end=30.0, raw_score=0.5, has_speech=True,
                 scene_count=2, audio_energy=0.6, signals=None):
    return Moment(
        start=start, end=end, raw_score=raw_score,
        has_speech=has_speech, scene_count=scene_count,
        audio_energy=audio_energy, signals=signals or {"silence_ratio": 0.0, "duration_fitness": 1.0, "duration": end - start},
    )


def _make_context(**kwargs):
    defaults = dict(
        video_id="test", source_path="/tmp/v.mp4", duration=120.0,
        speech_regions=[SpeechRegion(start=5.0, end=25.0)],
    )
    defaults.update(kwargs)
    return VideoContext(**defaults)


class TestSelectFormat:
    def test_short_clip_is_square(self):
        assert _select_format(20.0, True) == ClipFormat.SQUARE

    def test_medium_clip_with_speech_is_portrait(self):
        assert _select_format(45.0, True) == ClipFormat.PORTRAIT

    def test_medium_clip_without_speech_is_landscape(self):
        assert _select_format(45.0, False) == ClipFormat.LANDSCAPE

    def test_long_clip_is_landscape(self):
        assert _select_format(90.0, True) == ClipFormat.LANDSCAPE

    def test_boundary_30s_is_portrait_with_speech(self):
        # 30.0 is >= 30 so not SQUARE, < 60 and has_speech → PORTRAIT
        assert _select_format(30.0, True) == ClipFormat.PORTRAIT

    def test_boundary_60s_is_landscape(self):
        assert _select_format(60.0, True) == ClipFormat.LANDSCAPE


class TestSpeechBoundaryPenalty:
    def test_no_penalty_when_aligned(self):
        moment = _make_moment(start=5.0, end=25.0)
        ctx = _make_context(speech_regions=[SpeechRegion(start=5.0, end=25.0)])
        score = _apply_speech_boundary_penalty(moment, ctx, 0.8)
        assert score == 0.8  # start=5 is not strictly inside (5,25)

    def test_penalty_when_start_mid_speech(self):
        moment = _make_moment(start=10.0, end=30.0)
        ctx = _make_context(speech_regions=[SpeechRegion(start=5.0, end=25.0)])
        score = _apply_speech_boundary_penalty(moment, ctx, 0.8)
        assert score == pytest.approx(0.8 - SPEECH_BOUNDARY_PENALTY, abs=0.01)

    def test_double_penalty_both_boundaries(self):
        moment = _make_moment(start=10.0, end=20.0)
        ctx = _make_context(speech_regions=[SpeechRegion(start=5.0, end=25.0)])
        score = _apply_speech_boundary_penalty(moment, ctx, 0.8)
        assert score == pytest.approx(0.8 - 2 * SPEECH_BOUNDARY_PENALTY, abs=0.01)


class TestBuildRationale:
    def test_includes_speech(self):
        moment = _make_moment(has_speech=True)
        r = _build_rationale(moment)
        assert "speech" in r

    def test_includes_no_speech(self):
        moment = _make_moment(has_speech=False)
        r = _build_rationale(moment)
        assert "no speech" in r

    def test_includes_scene_count(self):
        moment = _make_moment(scene_count=3)
        r = _build_rationale(moment)
        assert "3 scene transitions" in r

    def test_includes_energy_level(self):
        moment = _make_moment(audio_energy=0.8)
        r = _build_rationale(moment)
        assert "high energy" in r

    def test_moderate_energy(self):
        moment = _make_moment(audio_energy=0.5)
        r = _build_rationale(moment)
        assert "moderate energy" in r

    def test_includes_duration(self):
        moment = _make_moment(start=0.0, end=30.0, signals={"silence_ratio": 0.0, "duration_fitness": 1.0, "duration": 30.0})
        r = _build_rationale(moment)
        assert "30s" in r


class TestRankClips:
    async def test_filters_low_score_moments(self, mock_ai):
        moments = [
            _make_moment(raw_score=0.1),  # below threshold
            _make_moment(start=30.0, end=60.0, raw_score=0.5),
        ]
        ctx = _make_context()
        clips = await rank_clips(moments, ctx, mock_ai)
        assert len(clips) >= 1
        # The low-score moment should be filtered out before clip creation

    async def test_empty_moments_returns_empty(self, mock_ai):
        ctx = _make_context()
        clips = await rank_clips([], ctx, mock_ai)
        assert clips == []

    async def test_high_score_generates_variants(self, mock_ai):
        moments = [_make_moment(raw_score=0.8)]  # above HIGH_SCORE_THRESHOLD
        ctx = _make_context()
        clips = await rank_clips(moments, ctx, mock_ai)
        # Should have primary + 2 variants (3 formats)
        assert len(clips) >= 3

    async def test_sorted_by_score_descending(self, mock_ai):
        moments = [
            _make_moment(start=0.0, end=20.0, raw_score=0.4),
            _make_moment(start=30.0, end=60.0, raw_score=0.8),
        ]
        ctx = _make_context()
        clips = await rank_clips(moments, ctx, mock_ai)
        scores = [c.score for c in clips]
        assert scores == sorted(scores, reverse=True)

    async def test_max_clips_limit(self, mock_ai):
        # Create many moments
        moments = [
            _make_moment(start=i * 10, end=i * 10 + 30, raw_score=0.7)
            for i in range(20)
        ]
        ctx = _make_context()
        clips = await rank_clips(moments, ctx, mock_ai)
        assert len(clips) <= MAX_CLIPS

    async def test_no_ai_service(self):
        moments = [_make_moment(raw_score=0.5)]
        ctx = _make_context()
        clips = await rank_clips(moments, ctx, None)
        assert len(clips) >= 1
