"""
Context Store — persistence layer for the Context Graph.

Local mode: in-memory dict store.
Production: PostgreSQL (swap implementation, same interface).
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional

from src.context.models import VideoContext, JobStatus

logger = logging.getLogger(__name__)


class ContextStore:
    """
    In-memory context store for local development.

    Interface is designed to be swappable with a PostgreSQL implementation.
    All methods are async-ready for future DB migration.
    """

    def __init__(self):
        self._store: Dict[str, VideoContext] = {}  # keyed by video_id
        self._by_job: Dict[str, str] = {}          # job_id → video_id
        logger.info("ContextStore initialized (in-memory)")

    async def save(self, context: VideoContext) -> VideoContext:
        """Save or update a context graph."""
        context.updated_at = datetime.utcnow()
        self._store[context.video_id] = context
        self._by_job[context.job_id] = context.video_id
        logger.debug(f"Saved context for video={context.video_id}, job={context.job_id}")
        return context

    async def get_by_video_id(self, video_id: str) -> Optional[VideoContext]:
        """Retrieve context by video ID."""
        return self._store.get(video_id)

    async def get_by_job_id(self, job_id: str) -> Optional[VideoContext]:
        """Retrieve context by job ID."""
        video_id = self._by_job.get(job_id)
        if video_id:
            return self._store.get(video_id)
        return None

    async def list_all(self, limit: int = 50) -> List[VideoContext]:
        """List all stored contexts (most recent first)."""
        contexts = sorted(
            self._store.values(),
            key=lambda c: c.created_at,
            reverse=True,
        )
        return contexts[:limit]

    async def delete(self, video_id: str) -> bool:
        """Delete a context graph."""
        if video_id in self._store:
            ctx = self._store.pop(video_id)
            self._by_job.pop(ctx.job_id, None)
            return True
        return False

    async def update_status(self, video_id: str, status: JobStatus) -> Optional[VideoContext]:
        """Update job status on a context."""
        ctx = self._store.get(video_id)
        if ctx:
            ctx.status = status
            ctx.updated_at = datetime.utcnow()
            return ctx
        return None

    def count(self) -> int:
        return len(self._store)
