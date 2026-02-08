"""
Job Manager — orchestrates Video Sense analysis jobs.

Responsibilities:
- Accept job requests
- Track job state (queued → processing → complete/failed)
- Execute the analysis pipeline
- Enforce idempotency (same video_id → return existing result)
- Retry on failure
"""

import asyncio
import logging
import time
from datetime import datetime
from typing import Callable, Awaitable, Optional, Dict, Any

from src.context.models import (
    VideoContext, JobRequest, JobState, JobStatus,
)
from src.context.context_store import ContextStore

logger = logging.getLogger(__name__)


class JobManager:
    """
    Manages the lifecycle of Video Sense analysis jobs.

    Pipeline is injected at init — the job manager doesn't know
    what analysis steps exist, it just runs the pipeline function.
    """

    def __init__(
        self,
        context_store: ContextStore,
        pipeline_fn: Optional[Callable[[VideoContext], Awaitable[VideoContext]]] = None,
    ):
        self.context_store = context_store
        self.pipeline_fn = pipeline_fn
        self._jobs: Dict[str, JobState] = {}
        self._active_jobs: int = 0
        self._max_concurrent: int = 5
        logger.info("JobManager initialized")

    def set_pipeline(self, pipeline_fn: Callable[[VideoContext], Awaitable[VideoContext]]):
        """Set the analysis pipeline function."""
        self.pipeline_fn = pipeline_fn

    async def submit(self, request: JobRequest) -> VideoContext:
        """
        Submit a video for analysis.

        Idempotent: if the video has already been processed (status=complete),
        returns the existing context without reprocessing.
        """
        # Check for existing complete context
        existing = await self.context_store.get_by_video_id(request.video_id)
        if existing and existing.status == JobStatus.COMPLETE:
            logger.info(f"Video {request.video_id} already processed, returning existing context")
            return existing

        # Create new context
        context = VideoContext(
            video_id=request.video_id,
            creator_id=request.creator_id,
            source_path=request.source_path,
            tier=request.tier,
            status=JobStatus.QUEUED,
        )

        # Create job state
        job_state = JobState(
            job_id=context.job_id,
            video_id=request.video_id,
            status=JobStatus.QUEUED,
        )
        self._jobs[job_state.job_id] = job_state

        # Save initial context
        await self.context_store.save(context)
        logger.info(f"Job {context.job_id} queued for video {request.video_id}")

        return context

    async def execute(self, video_id: str) -> VideoContext:
        """
        Execute the analysis pipeline for a video.

        This is the main processing method — runs all signal extractors
        and populates the context graph.
        """
        context = await self.context_store.get_by_video_id(video_id)
        if not context:
            raise ValueError(f"No context found for video {video_id}")

        if not self.pipeline_fn:
            raise RuntimeError("No pipeline function configured")

        job_state = self._jobs.get(context.job_id)

        # Mark as processing
        context.status = JobStatus.PROCESSING
        if job_state:
            job_state.status = JobStatus.PROCESSING
            job_state.started_at = datetime.utcnow()
        await self.context_store.save(context)

        self._active_jobs += 1
        start_time = time.time()

        try:
            # Run the pipeline
            context = await self.pipeline_fn(context)

            # Mark complete
            context.status = JobStatus.COMPLETE
            if job_state:
                job_state.status = JobStatus.COMPLETE
                job_state.completed_at = datetime.utcnow()

            elapsed = time.time() - start_time
            logger.info(
                f"Job {context.job_id} complete for video {video_id} "
                f"({elapsed:.2f}s)"
            )

        except Exception as e:
            context.status = JobStatus.FAILED
            if job_state:
                job_state.status = JobStatus.FAILED
                job_state.error = str(e)
                job_state.retries += 1
            logger.error(f"Job {context.job_id} failed: {e}", exc_info=True)

        finally:
            self._active_jobs -= 1
            await self.context_store.save(context)

        return context

    async def submit_and_execute(self, request: JobRequest) -> VideoContext:
        """Submit a job and immediately execute it (synchronous convenience)."""
        context = await self.submit(request)
        if context.status == JobStatus.COMPLETE:
            return context  # Already processed (idempotent)
        return await self.execute(request.video_id)

    def get_job_state(self, job_id: str) -> Optional[JobState]:
        return self._jobs.get(job_id)

    def get_stats(self) -> Dict[str, Any]:
        status_counts = {}
        for job in self._jobs.values():
            status_counts[job.status.value] = status_counts.get(job.status.value, 0) + 1
        return {
            "total_jobs": len(self._jobs),
            "active_jobs": self._active_jobs,
            "by_status": status_counts,
        }
