"""Tests for the in-memory ContextStore."""

import pytest

from src.context.models import JobStatus, VideoContext
from src.context.context_store import ContextStore


class TestContextStoreSave:
    async def test_save_and_retrieve(self, context_store):
        ctx = VideoContext(video_id="v1", source_path="/tmp/v1.mp4")
        saved = await context_store.save(ctx)
        assert saved.video_id == "v1"

        retrieved = await context_store.get_by_video_id("v1")
        assert retrieved is not None
        assert retrieved.video_id == "v1"

    async def test_save_updates_timestamp(self, context_store):
        ctx = VideoContext(video_id="v1")
        original_time = ctx.updated_at
        await context_store.save(ctx)
        assert ctx.updated_at >= original_time

    async def test_save_overwrites_existing(self, context_store):
        ctx = VideoContext(video_id="v1", duration=10.0)
        await context_store.save(ctx)
        ctx.duration = 20.0
        await context_store.save(ctx)

        retrieved = await context_store.get_by_video_id("v1")
        assert retrieved.duration == 20.0

    async def test_count(self, context_store):
        assert context_store.count() == 0
        await context_store.save(VideoContext(video_id="v1"))
        assert context_store.count() == 1
        await context_store.save(VideoContext(video_id="v2"))
        assert context_store.count() == 2


class TestContextStoreRetrieval:
    async def test_get_by_video_id_missing(self, context_store):
        result = await context_store.get_by_video_id("nonexistent")
        assert result is None

    async def test_get_by_job_id(self, context_store):
        ctx = VideoContext(video_id="v1")
        await context_store.save(ctx)
        retrieved = await context_store.get_by_job_id(ctx.job_id)
        assert retrieved is not None
        assert retrieved.video_id == "v1"

    async def test_get_by_job_id_missing(self, context_store):
        result = await context_store.get_by_job_id("nonexistent")
        assert result is None


class TestContextStoreList:
    async def test_list_all_empty(self, context_store):
        results = await context_store.list_all()
        assert results == []

    async def test_list_all_returns_all(self, context_store):
        for i in range(3):
            await context_store.save(VideoContext(video_id=f"v{i}"))
        results = await context_store.list_all()
        assert len(results) == 3

    async def test_list_all_respects_limit(self, context_store):
        for i in range(5):
            await context_store.save(VideoContext(video_id=f"v{i}"))
        results = await context_store.list_all(limit=2)
        assert len(results) == 2


class TestContextStoreDelete:
    async def test_delete_existing(self, context_store):
        ctx = VideoContext(video_id="v1")
        await context_store.save(ctx)
        assert await context_store.delete("v1") is True
        assert await context_store.get_by_video_id("v1") is None
        assert context_store.count() == 0

    async def test_delete_nonexistent(self, context_store):
        assert await context_store.delete("nonexistent") is False

    async def test_delete_clears_job_index(self, context_store):
        ctx = VideoContext(video_id="v1")
        await context_store.save(ctx)
        job_id = ctx.job_id
        await context_store.delete("v1")
        assert await context_store.get_by_job_id(job_id) is None


class TestContextStoreUpdateStatus:
    async def test_update_status(self, context_store):
        ctx = VideoContext(video_id="v1", status=JobStatus.QUEUED)
        await context_store.save(ctx)

        updated = await context_store.update_status("v1", JobStatus.PROCESSING)
        assert updated is not None
        assert updated.status == JobStatus.PROCESSING

    async def test_update_status_nonexistent(self, context_store):
        result = await context_store.update_status("nonexistent", JobStatus.FAILED)
        assert result is None
