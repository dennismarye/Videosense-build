"""
Mock Google Generative AI service for local development.

Returns realistic stub responses for safety checks, tagging,
and description alignment — no Gemini API key required.
"""

import logging
import time
import os
from typing import Dict, List, Any, Optional

from src.config.settings import settings

logger = logging.getLogger(__name__)


class MockGoogleGenerativeService:
    """
    Drop-in replacement for EnhancedGoogleGenerativeService.
    Returns deterministic mock results so the full pipeline can run locally.
    """

    def __init__(self):
        self.model_name = "mock-gemini-local"
        self.timeout = settings.GEMINI_TIMEOUT
        logger.info("MockGoogleGenerativeService initialized (no API calls)")

    def get_health_status(self) -> Dict[str, Any]:
        return {
            "gemini_ai": "mock",
            "slack_integration": "disabled",
            "model": self.model_name,
            "timeout": self.timeout,
        }

    async def analyze_video_safety_and_tags(
        self, video_path: str, circo_post: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Return a mock SAFE result with sample tags."""
        job_id = circo_post.get("jobId", "unknown")
        logger.info(f"[MOCK] Analyzing safety & tags for job {job_id}: {video_path}")

        # Determine file size for context
        file_size_mb = 0
        if os.path.exists(video_path):
            file_size_mb = round(os.path.getsize(video_path) / (1024 * 1024), 2)

        return {
            "jobId": job_id,
            "safety_check": {
                "contentFlag": "SAFE",
                "reason": "Mock analysis: content appears safe for all audiences",
            },
            "tags": [
                {
                    "category": "Entertainment & Gossip",
                    "subcategory": ["Viral Moments", "Memes & Trends"],
                },
                {
                    "category": "Lifestyle & Culture",
                    "subcategory": ["Daily Vlogs"],
                },
            ],
            "aiContext": (
                f"Mock analysis of video ({file_size_mb}MB). "
                "The video appears to contain general entertainment content "
                "suitable for a broad audience. No policy violations detected."
            ),
            "video_info": self._extract_video_info(circo_post),
            "analysis_metadata": {
                "model": self.model_name,
                "timestamp": int(time.time()),
                "processing_time": None,
                "mock": True,
            },
        }

    async def analyze_description_alignment(
        self, user_caption: str, ai_context: str
    ) -> Dict[str, Any]:
        """Return a mock alignment score."""
        logger.info(f"[MOCK] Analyzing description alignment: {user_caption[:80]}...")

        if not user_caption.strip():
            return {
                "alignmentScore": 0,
                "alignmentLevel": "N/A",
                "justification": "No description provided",
                "suggestion": "Add a description to enable alignment analysis",
            }

        # Simple heuristic: longer captions score higher
        caption_len = len(user_caption.strip())
        if caption_len > 100:
            score = 85
        elif caption_len > 50:
            score = 70
        elif caption_len > 20:
            score = 55
        else:
            score = 35

        level = (
            "EXCELLENT" if score >= 90
            else "GOOD" if score >= 70
            else "FAIR" if score >= 45
            else "POOR"
        )

        return {
            "alignmentScore": score,
            "alignmentLevel": level,
            "justification": f"Mock analysis: caption length ({caption_len} chars) suggests {level.lower()} alignment",
            "suggestion": (
                "Caption looks good!" if score >= 70
                else "Consider adding more detail to your caption for better discoverability"
            ),
            "analysis_metadata": {
                "model": self.model_name,
                "timestamp": int(time.time()),
                "mock": True,
            },
        }

    async def send_safety_notification(
        self,
        analysis_result: Dict[str, Any],
        video_info: Dict[str, Any],
        circo_post: Dict[str, Any],
    ):
        """Log the notification instead of sending to Slack."""
        safety_check = analysis_result.get("safety_check", {})
        content_flag = safety_check.get("contentFlag", "UNKNOWN")
        job_id = analysis_result.get("jobId", "unknown")
        logger.info(
            f"[MOCK SLACK] Safety notification: job={job_id}, flag={content_flag}, "
            f"reason={safety_check.get('reason', 'N/A')}"
        )

    def _extract_video_info(self, circo_post: Dict[str, Any]) -> Dict[str, Any]:
        try:
            media_files = circo_post.get("files", [])
            for media_item in media_files:
                if media_item.get("fileType") == "Video":
                    return {
                        "name": media_item.get("name", "unknown"),
                        "url": media_item.get("original")
                        or media_item.get("cachedOriginal", "unknown"),
                        "id": media_item.get("id", "unknown"),
                    }
            return {"name": "unknown", "url": "unknown", "id": "unknown"}
        except Exception:
            return {"name": "error", "url": "error", "id": "error"}

    async def test_ai_connection(self) -> Dict[str, Any]:
        return {
            "status": "mock",
            "model": self.model_name,
            "test_response": "Mock AI service — no real API calls",
            "timestamp": int(time.time()),
        }
