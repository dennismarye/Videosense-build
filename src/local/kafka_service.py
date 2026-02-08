"""
Local Kafka replacement — in-memory async queue.

Messages are stored in-memory and can be triggered via the local dev API.
No Kafka broker, no confluent-kafka dependency needed.
"""

import asyncio
import json
import logging
import time
from typing import Dict, Any, List, Callable, Optional

logger = logging.getLogger(__name__)


class LocalKafkaService:
    """Drop-in replacement for KafkaService that uses an in-memory asyncio queue."""

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._produced_messages: List[Dict[str, Any]] = []
        self._message_handler: Optional[Callable] = None
        self._running = False

        logger.info("LocalKafkaService initialized (in-memory queue, no broker)")

    def _get_queue(self, topic: str) -> asyncio.Queue:
        if topic not in self._queues:
            self._queues[topic] = asyncio.Queue()
        return self._queues[topic]

    # ── Producer ──────────────────────────────────────────────

    async def produce(self, topic: str, data: Dict[str, Any]):
        """Store produced message locally and log it."""
        message = {
            "topic": topic,
            "timestamp": int(time.time() * 1000),
            "message_type": "local",
            "data": data,
        }
        self._produced_messages.append(message)
        logger.info(
            f"[LOCAL] Produced to '{topic}': jobId={data.get('jobId', '?')}"
        )
        return {
            "status": "success",
            "message": f"Local message stored for topic {topic}",
            "jobId": data.get("jobId", "unknown"),
        }

    async def produce_safety_result(self, data: Dict[str, Any]):
        return await self.produce("classification.safety_check_passed", data)

    async def produce_quality_result(self, data: Dict[str, Any]):
        return await self.produce("classification.quality_analysis", data)

    # ── Consumer ──────────────────────────────────────────────

    async def consume(self, topics: List[str], message_handler, stop_event=None):
        """
        In local mode the consumer doesn't poll a broker.
        Instead, messages are injected via `enqueue()` and processed here.
        """
        self._message_handler = message_handler
        self._running = True
        logger.info(f"[LOCAL] Consumer listening on in-memory queues: {topics}")

        while stop_event is None or not stop_event.is_set():
            for topic in topics:
                queue = self._get_queue(topic)
                try:
                    message = queue.get_nowait()
                    logger.info(f"[LOCAL] Processing message from '{topic}'")
                    await message_handler(message)
                except asyncio.QueueEmpty:
                    pass
            await asyncio.sleep(0.5)

    async def enqueue(self, topic: str, message: Dict[str, Any]):
        """Inject a message into the local queue (called by dev API endpoints)."""
        queue = self._get_queue(topic)
        await queue.put(message)
        logger.info(f"[LOCAL] Enqueued message to '{topic}': jobId={message.get('jobId', '?')}")

    async def close_consumer(self):
        self._running = False
        logger.info("[LOCAL] Consumer stopped")

    # ── Introspection ─────────────────────────────────────────

    def get_produced_messages(self) -> List[Dict[str, Any]]:
        """Return all messages that were produced (for local inspection)."""
        return self._produced_messages

    def clear_produced_messages(self):
        self._produced_messages.clear()

    def get_topics_info(self) -> Dict[str, str]:
        return {
            "mode": "local",
            "queues": list(self._queues.keys()),
            "produced_count": len(self._produced_messages),
        }

    def get_health_status(self) -> Dict[str, Any]:
        return {
            "mode": "local",
            "status": "healthy",
            "queues": list(self._queues.keys()),
            "produced_messages": len(self._produced_messages),
        }
