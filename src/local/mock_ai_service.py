"""
Mock AI Service — deterministic AI responses for local development.

Returns plausible results derived from V0 signals (duration, scene count,
speech regions, audio energy) without any real AI calls.

Swap with GeminiAIService by changing AI_SERVICE_TYPE in settings.
"""

import logging
import uuid
from typing import List, Optional

from src.context.models import (
    ClipFormat,
    CropRegion,
    DescriptionVariant,
    Entity,
    HookScore,
    NarrativeBeat,
    PLATFORM_DESCRIPTION_LIMITS,
    Platform,
    QualityFlag,
    SuggestedClip,
    ThumbnailCandidate,
    TitleStyle,
    TitleVariant,
    Topic,
    VideoContext,
)

logger = logging.getLogger(__name__)


class MockAIService:
    """Deterministic AI mock — derives plausible results from V0 signals."""

    def __init__(self):
        logger.info("MockAIService initialized (no AI API calls)")

    async def analyze_hook(
        self, video_path: str, duration: float, scenes: list, speech_regions: list, audio_energy: float,
    ) -> HookScore:
        # Compute base score from early signals (first 5 seconds)
        factors = []
        early_scene = any(s.start < 5.0 for s in scenes if hasattr(s, "start"))
        early_speech = any(r.start < 3.0 for r in speech_regions if hasattr(r, "start"))

        score = 0.0
        if early_scene:
            score += 0.3
            factors.append(f"scene change in first 5s")
        if early_speech:
            score += 0.35
            factors.append(f"voice onset within 3s")
        if audio_energy > 0.5:
            score += 0.2
            factors.append(f"strong audio energy ({audio_energy:.1f})")
        if duration > 10:
            score += 0.15
            factors.append("adequate duration for hook development")

        score = min(score, 1.0)
        analysis = f"Hook analysis: {', '.join(factors)}." if factors else "Weak hook — no strong opening signals detected."

        return HookScore(score=round(score, 3), analysis=analysis)

    async def generate_summary(
        self, video_path: str, transcript: Optional[str], duration: float, scene_count: int,
    ) -> str:
        mins = int(duration // 60)
        secs = int(duration % 60)
        dur_str = f"{mins}m{secs}s" if mins > 0 else f"{secs}s"

        if transcript and len(transcript) > 50:
            # Use first sentence of transcript as basis
            first_sentence = transcript.split(".")[0].strip()
            if len(first_sentence) > 20:
                return f"{dur_str} video covering: {first_sentence}. Contains {scene_count} distinct scenes."

        return f"A {dur_str} video with {scene_count} scene{'s' if scene_count != 1 else ''} and {'spoken content' if transcript else 'no detected speech'}."

    async def rank_clips(
        self, moments: List[dict], video_path: str, duration: float,
    ) -> List[SuggestedClip]:
        # Mock: pass through moments as-is with rationale strings
        clips = []
        for m in moments:
            clip_dur = m["end"] - m["start"]
            rationale_parts = []
            if m.get("has_speech"):
                rationale_parts.append("speech present")
            if m.get("scene_count", 0) > 1:
                rationale_parts.append(f"{m['scene_count']} scene transitions")
            if m.get("audio_energy", 0) > 0.5:
                rationale_parts.append("high audio energy")
            if not rationale_parts:
                rationale_parts.append("visual content segment")

            clips.append(SuggestedClip(
                clip_id=str(uuid.uuid4()),
                start=m["start"],
                end=m["end"],
                score=round(m.get("raw_score", 0.5), 3),
                rationale=" + ".join(rationale_parts),
                format=ClipFormat.LANDSCAPE,
            ))

        return sorted(clips, key=lambda c: c.score, reverse=True)

    async def score_thumbnails(
        self, candidates: List[dict], video_path: str,
    ) -> List[ThumbnailCandidate]:
        # Mock: return candidates with slightly adjusted scores
        results = []
        for c in candidates:
            results.append(ThumbnailCandidate(
                timestamp=c["timestamp"],
                score=round(c.get("score", 0.5), 3),
                reasons=c.get("reasons", ["ai_scored"]),
                frame_path=c.get("frame_path"),
            ))
        return sorted(results, key=lambda t: t.score, reverse=True)

    async def extract_topics(
        self, transcript: Optional[str], video_path: str, duration: float,
    ) -> List[Topic]:
        topics = [Topic(label="video content", confidence=0.8, timestamps=[0.0])]
        if transcript and len(transcript) > 100:
            topics.append(Topic(label="spoken discussion", confidence=0.7, timestamps=[0.0]))
        if duration > 120:
            topics.append(Topic(label="long-form content", confidence=0.6, timestamps=[0.0]))
        return topics

    async def extract_entities(
        self, transcript: Optional[str], video_path: str,
    ) -> List[Entity]:
        # Mock: no real entity extraction without AI
        return []

    async def detect_narrative_beats(
        self, video_path: str, scenes: list, transcript: Optional[str], duration: float,
    ) -> List[NarrativeBeat]:
        beats = []
        if duration > 5:
            beats.append(NarrativeBeat(type="intro", timestamp=0.0, description="Video opening"))
        if duration > 30 and len(scenes) > 2:
            mid = duration / 2
            beats.append(NarrativeBeat(type="development", timestamp=mid, description="Core content section"))
        if duration > 10:
            beats.append(NarrativeBeat(type="conclusion", timestamp=max(0, duration - 3), description="Video closing"))
        return beats

    # V1.1: Teaser Engine

    async def generate_teaser_titles(
        self, summary: Optional[str], topics: list, platforms: List[str],
        max_chars_per_platform: dict,
    ) -> dict:
        base = summary[:40].rstrip(".") if summary else "Check this out"
        result = {}
        for platform in platforms:
            max_chars = max_chars_per_platform.get(platform, 100)
            if len(topics) > 0:
                label = topics[0].label if hasattr(topics[0], "label") else str(topics[0])
                title = f"{base} — {label}"
            else:
                title = base
            result[platform] = title[:max_chars]
        return result

    async def generate_teaser_hashtags(
        self, topics: list, platforms: List[str],
        max_hashtags_per_platform: dict,
    ) -> dict:
        base_tags = []
        for t in topics[:3]:
            label = t.label if hasattr(t, "label") else str(t)
            base_tags.append(f"#{label.replace(' ', '')}")
        base_tags.extend(["#circo", "#creator", "#content"])
        result = {}
        for platform in platforms:
            max_tags = max_hashtags_per_platform.get(platform, 5)
            result[platform] = base_tags[:max_tags]
        return result

    # V1.2: Content Packaging

    async def generate_titles(
        self, context: "VideoContext", platforms: List["Platform"],
    ) -> List["TitleVariant"]:
        """Generate deterministic title variants from context signals."""
        base_text = ""
        if context.summary:
            base_text = context.summary.split(".")[0].strip()
        elif context.topics:
            base_text = context.topics[0].label
        else:
            base_text = "Video content"

        styles = [
            TitleStyle.HOOK,
            TitleStyle.DESCRIPTIVE,
            TitleStyle.QUESTION,
        ]

        titles = []
        for platform in platforms:
            for i, style in enumerate(styles):
                if style == TitleStyle.HOOK:
                    text = base_text[:90]
                elif style == TitleStyle.DESCRIPTIVE:
                    text = f"About: {base_text}"[:100]
                elif style == TitleStyle.QUESTION:
                    text = f"Have you seen {base_text}?"[:100]
                else:
                    text = base_text[:100]

                # Ensure non-empty
                if not text:
                    text = "Untitled"

                confidence = round(max(0.1, 0.9 - (i * 0.2)), 3)
                titles.append(TitleVariant(
                    text=text,
                    style=style,
                    platform=platform,
                    confidence=confidence,
                ))

        return titles

    async def generate_descriptions(
        self, context: "VideoContext", platforms: List["Platform"],
    ) -> List["DescriptionVariant"]:
        """Generate deterministic description variants from context signals."""
        # Build base description from available signals
        parts = []
        if context.summary:
            parts.append(context.summary)
        if context.topics:
            topic_labels = [t.label for t in context.topics[:3]]
            parts.append(f"Topics: {', '.join(topic_labels)}")

        base_desc = " | ".join(parts) if parts else "Video content"

        # Build chapter markers from speech regions
        has_chapters = len(context.speech_regions) >= 3
        chapter_text = ""
        if has_chapters:
            chapter_lines = []
            for sr in context.speech_regions[:5]:
                mins = int(sr.start // 60)
                secs = int(sr.start % 60)
                ts = f"{mins}:{secs:02d}"
                label = sr.transcript[:30] if sr.transcript else "Section"
                chapter_lines.append(f"{ts} — {label}")
            chapter_text = "\n".join(chapter_lines)

        descriptions = []
        for platform in platforms:
            limit = PLATFORM_DESCRIPTION_LIMITS.get(platform, 5000)

            # Variant 1: plain description
            text1 = base_desc[:limit]
            descriptions.append(DescriptionVariant(
                text=text1,
                platform=platform,
                includes_cta=False,
                includes_timestamps=False,
            ))

            # Variant 2: with CTA
            cta_text = f"{base_desc}\n\nFollow for more content!"[:limit]
            descriptions.append(DescriptionVariant(
                text=cta_text,
                platform=platform,
                includes_cta=True,
                includes_timestamps=False,
            ))

            # Variant 3: with timestamps (if chapters available)
            if has_chapters:
                ts_text = f"{base_desc}\n\n{chapter_text}"[:limit]
                descriptions.append(DescriptionVariant(
                    text=ts_text,
                    platform=platform,
                    includes_cta=False,
                    includes_timestamps=True,
                ))

        return descriptions

    async def generate_hashtags(
        self, context: "VideoContext", platforms: List["Platform"],
    ) -> dict:
        """Generate raw hashtags per platform from context topics."""
        base_tags = []
        for t in context.topics[:5]:
            base_tags.append(f"#{t.label.replace(' ', '')}")
        base_tags.extend(["#circo", "#creator", "#content"])

        result = {}
        for platform in platforms:
            result[platform] = list(base_tags)
        return result

    async def score_thumbnail_crop(
        self, frame_path: str, crop: "CropRegion",
    ) -> float:
        """Deterministic crop scoring: area ratio + center weighting."""
        frame_area = crop.frame_width * crop.frame_height
        crop_area = crop.width * crop.height
        area_ratio = crop_area / max(frame_area, 1)

        crop_cx = crop.x + crop.width / 2
        crop_cy = crop.y + crop.height / 2
        frame_cx = crop.frame_width / 2
        frame_cy = crop.frame_height / 2

        dx = abs(crop_cx - frame_cx) / max(crop.frame_width / 2, 1)
        dy = abs(crop_cy - frame_cy) / max(crop.frame_height / 2, 1)
        center_penalty = (dx + dy) / 2

        score = 0.7 * area_ratio + 0.3 * (1.0 - center_penalty)
        return round(min(max(score, 0.0), 1.0), 3)
