"""Tests for JobManager and pipeline factories (V1.1)."""

import pytest

from src.context.models import (
    JobRequest,
    JobStatus,
    MonetizationTier,
    SeriesContext,
    TeaserMode,
    VideoContext,
)
from src.context.context_store import ContextStore
from src.jobs.job_manager import JobManager
from src.jobs.pipeline_v1_1 import _parse_series_context, create_v1_1_pipeline


# ── Helpers ──────────────────────────────────────────────────

async def _noop_pipeline(context: VideoContext) -> VideoContext:
    """Minimal pipeline that just marks fields."""
    context.duration = 42.0
    return context


async def _failing_pipeline(context: VideoContext) -> VideoContext:
    raise RuntimeError("Pipeline exploded")


# ── JobManager submit tests ──────────────────────────────────

class TestJobManagerSubmit:
    async def test_submit_creates_context(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        ctx = await mgr.submit(req)
        assert ctx.video_id == "v1"
        assert ctx.status == JobStatus.QUEUED

    async def test_submit_saves_to_store(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        await mgr.submit(req)
        stored = await context_store.get_by_video_id("v1")
        assert stored is not None

    async def test_submit_idempotent_for_complete(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")

        # First: submit and execute to completion
        await mgr.submit(req)
        await mgr.execute("v1")

        # Second: submit again should return existing
        ctx2 = await mgr.submit(req)
        assert ctx2.status == JobStatus.COMPLETE
        assert ctx2.duration == 42.0  # from the pipeline


# ── JobManager execute tests ─────────────────────────────────

class TestJobManagerExecute:
    async def test_execute_runs_pipeline(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        await mgr.submit(req)
        ctx = await mgr.execute("v1")
        assert ctx.status == JobStatus.COMPLETE
        assert ctx.duration == 42.0

    async def test_execute_no_context_raises(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        with pytest.raises(ValueError, match="No context found"):
            await mgr.execute("nonexistent")

    async def test_execute_no_pipeline_raises(self, context_store):
        mgr = JobManager(context_store, None)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        await mgr.submit(req)
        with pytest.raises(RuntimeError, match="No pipeline function"):
            await mgr.execute("v1")

    async def test_execute_failure_marks_failed(self, context_store):
        mgr = JobManager(context_store, _failing_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        await mgr.submit(req)
        ctx = await mgr.execute("v1")
        assert ctx.status == JobStatus.FAILED

    async def test_execute_failure_records_error(self, context_store):
        mgr = JobManager(context_store, _failing_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        await mgr.submit(req)
        await mgr.execute("v1")
        job_state = list(mgr._jobs.values())[0]
        assert job_state.error == "Pipeline exploded"
        assert job_state.retries == 1


# ── submit_and_execute tests ─────────────────────────────────

class TestJobManagerSubmitAndExecute:
    async def test_submit_and_execute(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        ctx = await mgr.submit_and_execute(req)
        assert ctx.status == JobStatus.COMPLETE

    async def test_submit_and_execute_idempotent(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        ctx1 = await mgr.submit_and_execute(req)
        ctx2 = await mgr.submit_and_execute(req)
        assert ctx1.job_id == ctx2.job_id


# ── Stats tests ──────────────────────────────────────────────

class TestJobManagerStats:
    async def test_initial_stats(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        stats = mgr.get_stats()
        assert stats["total_jobs"] == 0
        assert stats["active_jobs"] == 0

    async def test_stats_after_execution(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        await mgr.submit_and_execute(req)
        stats = mgr.get_stats()
        assert stats["total_jobs"] == 1
        assert stats["by_status"]["complete"] == 1


# ── set_pipeline tests ───────────────────────────────────────

class TestSetPipeline:
    async def test_set_pipeline(self, context_store):
        mgr = JobManager(context_store, None)
        mgr.set_pipeline(_noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        ctx = await mgr.submit_and_execute(req)
        assert ctx.status == JobStatus.COMPLETE


# ── V1.1 pipeline helpers ────────────────────────────────────

class TestParseSeriesContext:
    def test_returns_series_context(self):
        sc = SeriesContext(series_id="s1", series_title="Show", episode_number=1)
        ctx = VideoContext(video_id="v1", series_context=sc)
        result = _parse_series_context(ctx)
        assert result is not None
        assert result.series_id == "s1"

    def test_returns_none_when_missing(self):
        ctx = VideoContext(video_id="v1")
        result = _parse_series_context(ctx)
        assert result is None


# ── V1.1 pipeline factory ───────────────────────────────────

class TestTierPropagation:
    async def test_submit_propagates_pro_tier(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4", tier="pro")
        ctx = await mgr.submit(req)
        assert ctx.tier == MonetizationTier.PRO

    async def test_submit_defaults_to_free(self, context_store):
        mgr = JobManager(context_store, _noop_pipeline)
        req = JobRequest(video_id="v1", source_path="/tmp/v.mp4")
        ctx = await mgr.submit(req)
        assert ctx.tier == MonetizationTier.FREE


class TestCreateV1_1Pipeline:
    def test_returns_callable(self, mock_ai):
        fn = create_v1_1_pipeline(mock_ai)
        assert callable(fn)
