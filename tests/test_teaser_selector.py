"""Tests for the teaser selector — picks best teasers from clips."""

import pytest

from src.actions.teaser_selector import (
    BEAT_PROXIMITY_THRESHOLD,
    HARD_MAX_DURATION,
    HARD_MIN_DURATION,
    IDEAL_MAX_DURATION,
    IDEAL_MIN_DURATION,
    _clip_overlaps_beat,
    _compute_teaser_appeal,
    _deduplicate_overlapping,
    _find_narrative_alignment,
    _has_speech_overlap,
    _overlaps_significantly,
    select_teasers,
)
from src.context.models import (
    ClipFormat,
    NarrativeBeat,
    SeriesContext,
    SpeechRegion,
    SuggestedClip,
    Teaser,
    TeaserMode,
    VideoContext,
)


def _make_clip(clip_id="c1", start=0.0, end=20.0, score=0.8):
    return SuggestedClip(clip_id=clip_id, start=start, end=end, score=score, format=ClipFormat.LANDSCAPE)


def _make_context(clips=None, beats=None, speech=None, duration=120.0):
    return VideoContext(
        video_id="test",
        duration=duration,
        suggested_clips=clips or [],
        narrative_beats=beats or [],
        speech_regions=speech or [],
    )


# ── Teaser appeal scoring ───────────────────────────────────

class TestComputeTeaserAppeal:
    def test_base_score_is_half_clip_score(self):
        clip = _make_clip(score=0.8, start=0.0, end=10.0)  # 10s, outside ideal range
        appeal = _compute_teaser_appeal(clip, [], [])
        assert appeal == pytest.approx(0.4, abs=0.01)  # 0.8 * 0.5, no duration bonus

    def test_intro_beat_bonus(self):
        clip = _make_clip(start=0.0, end=10.0, score=0.8)  # 10s, no duration bonus
        beats = [NarrativeBeat(type="intro", timestamp=0.0)]
        appeal = _compute_teaser_appeal(clip, beats, [])
        # base (0.4) + intro (0.25) = 0.65
        assert appeal == pytest.approx(0.65, abs=0.01)

    def test_development_beat_bonus(self):
        clip = _make_clip(start=50.0, end=60.0, score=0.8)  # 10s, no duration bonus
        beats = [NarrativeBeat(type="development", timestamp=55.0)]
        appeal = _compute_teaser_appeal(clip, beats, [])
        # base (0.4) + development (0.20) = 0.60
        assert appeal == pytest.approx(0.60, abs=0.01)

    def test_speech_bonus(self):
        clip = _make_clip(start=0.0, end=10.0, score=0.8)  # 10s, no duration bonus
        speech = [SpeechRegion(start=2.0, end=8.0)]
        appeal = _compute_teaser_appeal(clip, [], speech)
        # base (0.4) + speech (0.15) = 0.55
        assert appeal == pytest.approx(0.55, abs=0.01)

    def test_ideal_duration_bonus(self):
        clip = _make_clip(start=0.0, end=20.0, score=0.8)  # 20s, in [15, 30]
        appeal = _compute_teaser_appeal(clip, [], [])
        # base (0.4) + duration (0.10) = 0.50
        assert appeal == pytest.approx(0.50, abs=0.01)

    def test_all_bonuses_cap_at_1(self):
        clip = _make_clip(start=0.0, end=20.0, score=1.0)
        beats = [NarrativeBeat(type="intro", timestamp=0.0)]
        speech = [SpeechRegion(start=5.0, end=15.0)]
        appeal = _compute_teaser_appeal(clip, beats, speech)
        assert appeal <= 1.0


# ── Beat overlap ─────────────────────────────────────────────

class TestClipOverlapsBeat:
    def test_beat_inside_clip(self):
        clip = _make_clip(start=10.0, end=30.0)
        beat = NarrativeBeat(type="intro", timestamp=15.0)
        assert _clip_overlaps_beat(clip, beat) is True

    def test_beat_within_proximity(self):
        clip = _make_clip(start=10.0, end=30.0)
        beat = NarrativeBeat(type="intro", timestamp=33.0)  # within 5s of end
        assert _clip_overlaps_beat(clip, beat) is True

    def test_beat_outside_proximity(self):
        clip = _make_clip(start=10.0, end=30.0)
        beat = NarrativeBeat(type="intro", timestamp=40.0)
        assert _clip_overlaps_beat(clip, beat) is False


# ── Narrative alignment ──────────────────────────────────────

class TestFindNarrativeAlignment:
    def test_returns_beat_type(self):
        clip = _make_clip(start=0.0, end=20.0)
        beats = [NarrativeBeat(type="intro", timestamp=5.0)]
        assert _find_narrative_alignment(clip, beats) == "intro"

    def test_returns_none_when_no_match(self):
        clip = _make_clip(start=50.0, end=60.0)
        beats = [NarrativeBeat(type="intro", timestamp=0.0)]
        assert _find_narrative_alignment(clip, beats) is None


# ── Speech overlap ───────────────────────────────────────────

class TestHasSpeechOverlap:
    def test_overlap_true(self):
        clip = _make_clip(start=0.0, end=20.0)
        speech = [SpeechRegion(start=5.0, end=15.0)]
        assert _has_speech_overlap(clip, speech) is True

    def test_no_overlap(self):
        clip = _make_clip(start=30.0, end=40.0)
        speech = [SpeechRegion(start=5.0, end=15.0)]
        assert _has_speech_overlap(clip, speech) is False


# ── Deduplication ────────────────────────────────────────────

class TestDeduplication:
    def test_no_overlap_keeps_both(self):
        t1 = Teaser(source_clip_id="c1", start=0.0, end=20.0, teaser_score=0.8)
        t2 = Teaser(source_clip_id="c2", start=30.0, end=50.0, teaser_score=0.7)
        result = _deduplicate_overlapping([t1, t2])
        assert len(result) == 2

    def test_significant_overlap_removes_lower(self):
        t1 = Teaser(source_clip_id="c1", start=0.0, end=20.0, teaser_score=0.8)
        t2 = Teaser(source_clip_id="c2", start=5.0, end=25.0, teaser_score=0.6)
        result = _deduplicate_overlapping([t1, t2])
        assert len(result) == 1
        assert result[0].teaser_score == 0.8

    def test_overlaps_significantly(self):
        t1 = Teaser(source_clip_id="c1", start=0.0, end=20.0, teaser_score=0.8)
        t2 = Teaser(source_clip_id="c2", start=5.0, end=25.0, teaser_score=0.6)
        assert _overlaps_significantly(t1, t2) is True

    def test_no_significant_overlap(self):
        t1 = Teaser(source_clip_id="c1", start=0.0, end=20.0, teaser_score=0.8)
        t2 = Teaser(source_clip_id="c2", start=18.0, end=40.0, teaser_score=0.6)
        # overlap = 2s, shorter = 20s, 2/20 = 0.10 < 0.5
        assert _overlaps_significantly(t1, t2) is False


# ── Full selection ───────────────────────────────────────────

class TestSelectTeasers:
    async def test_standard_mode(self, mock_ai):
        clips = [
            _make_clip("c1", 0.0, 20.0, 0.85),
            _make_clip("c2", 25.0, 50.0, 0.75),
            _make_clip("c3", 55.0, 80.0, 0.65),
        ]
        ctx = _make_context(clips=clips)
        teasers = await select_teasers(ctx, mock_ai, max_teasers=2)
        assert len(teasers) <= 2
        assert all(t.mode == TeaserMode.STANDARD for t in teasers)

    async def test_trailer_mode_with_series_context(self, mock_ai):
        clips = [
            _make_clip("c1", 0.0, 20.0, 0.8),
            _make_clip("c2", 40.0, 60.0, 0.7),
            _make_clip("c3", 80.0, 100.0, 0.6),
        ]
        ctx = _make_context(clips=clips, duration=120.0)
        series = SeriesContext(
            series_id="s1", series_title="Test", episode_number=1,
            teaser_mode=TeaserMode.TRAILER,
        )
        teasers = await select_teasers(ctx, mock_ai, max_teasers=3, series_context=series)
        assert all(t.mode == TeaserMode.TRAILER for t in teasers)

    async def test_no_clips_returns_empty(self, mock_ai):
        ctx = _make_context(clips=[])
        teasers = await select_teasers(ctx, mock_ai)
        assert teasers == []

    async def test_teasers_sorted_by_score(self, mock_ai):
        clips = [
            _make_clip("c1", 0.0, 20.0, 0.6),
            _make_clip("c2", 25.0, 50.0, 0.9),
            _make_clip("c3", 55.0, 80.0, 0.3),
        ]
        ctx = _make_context(clips=clips)
        teasers = await select_teasers(ctx, mock_ai, max_teasers=3)
        scores = [t.teaser_score for t in teasers]
        assert scores == sorted(scores, reverse=True)

    async def test_no_ai_service(self):
        clips = [_make_clip("c1", 0.0, 20.0, 0.8)]
        ctx = _make_context(clips=clips)
        teasers = await select_teasers(ctx, None)
        assert len(teasers) >= 1


# ── Hard duration enforcement tests ──────────────────────────

class TestHardDurationEnforcement:
    async def test_2s_clip_excluded(self, mock_ai):
        clips = [_make_clip("c1", 0.0, 2.0, 0.9)]
        ctx = _make_context(clips=clips)
        teasers = await select_teasers(ctx, mock_ai)
        assert len(teasers) == 0

    async def test_200s_clip_excluded(self, mock_ai):
        clips = [_make_clip("c1", 0.0, 200.0, 0.9)]
        ctx = _make_context(clips=clips)
        teasers = await select_teasers(ctx, mock_ai)
        assert len(teasers) == 0

    async def test_boundary_5s_included(self, mock_ai):
        clips = [_make_clip("c1", 0.0, 5.0, 0.5)]
        ctx = _make_context(clips=clips)
        teasers = await select_teasers(ctx, mock_ai)
        assert len(teasers) == 1

    async def test_boundary_90s_included(self, mock_ai):
        clips = [_make_clip("c1", 0.0, 90.0, 0.5)]
        ctx = _make_context(clips=clips)
        teasers = await select_teasers(ctx, mock_ai)
        assert len(teasers) == 1
