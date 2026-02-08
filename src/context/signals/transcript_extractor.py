"""
Transcript Extractor — uses faster-whisper for speech-to-text transcription.

Extracts audio from video, runs Whisper-based transcription, and maps
transcribed segments back to existing SpeechRegion objects by timestamp
overlap. Also extracts keywords via word frequency analysis.

Graceful degradation: if faster-whisper is not installed, logs a warning
and returns empty results.

Deterministic given the same model: same video + same model → same results.
"""

import logging
import os
import subprocess
import tempfile
from collections import Counter
from dataclasses import dataclass, field
from typing import List, Optional

from src.context.models import SpeechRegion

logger = logging.getLogger(__name__)

# ── Optional dependency ──────────────────────────────────────────

try:
    from faster_whisper import WhisperModel  # type: ignore[import-untyped]
    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    WhisperModel = None  # type: ignore[assignment,misc]

# ── Stopwords ────────────────────────────────────────────────────

STOPWORDS: set[str] = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "can", "could", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "it", "its", "they",
    "them", "their", "and", "or", "but", "if", "then", "so", "that", "this",
    "these", "those", "of", "in", "on", "at", "to", "for", "with", "from",
    "by", "as", "into", "about", "not", "no", "up", "out", "just", "like",
    "very", "really", "also", "too", "well", "oh", "um", "uh", "yeah",
    "okay", "ok",
}

# ── Result dataclass ─────────────────────────────────────────────

@dataclass
class TranscriptResult:
    """Container for transcript extraction output."""
    full_text: str = ""
    regions: List[SpeechRegion] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)


# ── Audio extraction ─────────────────────────────────────────────

def _extract_audio_to_wav(video_path: str, output_path: str) -> bool:
    """
    Extract audio from video to a 16kHz mono WAV file using FFmpeg.

    Returns True on success, False on failure.
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", video_path,
            "-vn",                  # no video
            "-acodec", "pcm_s16le", # 16-bit PCM
            "-ar", "16000",         # 16kHz sample rate
            "-ac", "1",             # mono
            "-y",                   # overwrite output
            output_path,
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0:
            logger.error(f"FFmpeg audio extraction failed: {result.stderr[:500]}")
            return False

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logger.error("FFmpeg produced empty or missing audio file")
            return False

        logger.info(f"Extracted audio to {output_path}")
        return True

    except subprocess.TimeoutExpired:
        logger.error(f"Audio extraction timed out for {video_path}")
        return False
    except Exception as e:
        logger.error(f"Audio extraction failed: {e}")
        return False


# ── Timestamp overlap mapping ────────────────────────────────────

def _segments_overlap(seg_start: float, seg_end: float, region_start: float, region_end: float) -> bool:
    """Check whether two time ranges overlap."""
    return seg_start < region_end and seg_end > region_start


def _map_segments_to_regions(
    whisper_segments: list,
    speech_regions: List[SpeechRegion],
) -> List[SpeechRegion]:
    """
    Map whisper segment transcripts onto existing SpeechRegion objects.

    If a whisper segment overlaps with a speech region, that region's
    transcript field is populated (or appended to).
    """
    # Build a dict of region index -> accumulated text
    region_texts: dict[int, list[str]] = {i: [] for i in range(len(speech_regions))}

    for segment in whisper_segments:
        seg_start = segment.start
        seg_end = segment.end
        seg_text = segment.text.strip()

        if not seg_text:
            continue

        for idx, region in enumerate(speech_regions):
            if _segments_overlap(seg_start, seg_end, region.start, region.end):
                region_texts[idx].append(seg_text)

    # Write accumulated transcripts back to regions
    enriched_regions: List[SpeechRegion] = []
    for idx, region in enumerate(speech_regions):
        texts = region_texts[idx]
        transcript = " ".join(texts) if texts else region.transcript
        enriched_regions.append(SpeechRegion(
            start=region.start,
            end=region.end,
            transcript=transcript,
            keywords=region.keywords,
        ))

    return enriched_regions


def _create_regions_from_segments(whisper_segments: list) -> List[SpeechRegion]:
    """Create new SpeechRegion objects directly from whisper segments."""
    regions: List[SpeechRegion] = []
    for segment in whisper_segments:
        text = segment.text.strip()
        if text:
            regions.append(SpeechRegion(
                start=segment.start,
                end=segment.end,
                transcript=text,
            ))
    return regions


# ── Keyword extraction ───────────────────────────────────────────

def _extract_keywords(text: str, top_n: int = 10) -> List[str]:
    """
    Extract keywords from text via word frequency analysis.

    Filters stopwords and returns the top N words by frequency.
    """
    if not text:
        return []

    # Tokenize: lowercase, keep only alphabetic tokens of length >= 2
    words = [
        w.lower()
        for w in text.split()
        if w.isalpha() and len(w) >= 2
    ]

    # Filter stopwords
    filtered = [w for w in words if w not in STOPWORDS]

    if not filtered:
        return []

    # Count and return top N
    counter = Counter(filtered)
    return [word for word, _count in counter.most_common(top_n)]


# ── Main extraction function ─────────────────────────────────────

async def extract_transcript(
    video_path: str,
    speech_regions: List[SpeechRegion],
    model_size: str = "base",
    device: str = "cpu",
    compute_type: str = "int8",
) -> TranscriptResult:
    """
    Extract transcript from video using faster-whisper.

    Steps:
      1. Extract audio from video to a temp WAV file (16kHz mono)
      2. Load faster-whisper WhisperModel
      3. Transcribe audio to get segments with timestamps
      4. Map whisper segments to existing SpeechRegion objects by overlap
      5. Extract keywords via word frequency analysis
      6. Clean up temp audio file

    Args:
        video_path: Path to the source video file.
        speech_regions: Pre-detected speech regions (from silence detector).
        model_size: Whisper model size (tiny, base, small, medium, large-v2).
        device: Compute device (cpu or cuda).
        compute_type: Quantization type (int8, float16, float32).

    Returns:
        TranscriptResult with full text, enriched regions, and keywords.
    """
    if not WHISPER_AVAILABLE:
        logger.warning(
            "faster-whisper is not installed. Skipping transcript extraction. "
            "Install with: pip install faster-whisper"
        )
        return TranscriptResult(regions=list(speech_regions))

    if not os.path.exists(video_path):
        logger.error(f"Video file not found: {video_path}")
        return TranscriptResult(regions=list(speech_regions))

    # Create a temp file for extracted audio
    tmp_fd, tmp_audio_path = tempfile.mkstemp(suffix=".wav")
    os.close(tmp_fd)

    try:
        # Step 1: Extract audio
        logger.info(f"Extracting audio from {video_path}")
        success = _extract_audio_to_wav(video_path, tmp_audio_path)
        if not success:
            logger.error("Audio extraction failed, returning empty transcript")
            return TranscriptResult(regions=list(speech_regions))

        # Step 2: Load model
        logger.info(f"Loading Whisper model: {model_size} (device={device}, compute_type={compute_type})")
        model = WhisperModel(model_size, device=device, compute_type=compute_type)

        # Step 3: Transcribe
        logger.info("Running transcription...")
        segments_iter, info = model.transcribe(tmp_audio_path)

        # Materialize the segment iterator so we can iterate multiple times
        segments = list(segments_iter)
        logger.info(
            f"Transcription complete: {len(segments)} segments, "
            f"language={info.language} (prob={info.language_probability:.2f})"
        )

        # Build full text
        full_text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())

        # Step 4: Map segments to speech regions
        if speech_regions:
            enriched_regions = _map_segments_to_regions(segments, speech_regions)
        else:
            # No pre-existing regions — create from whisper segments
            enriched_regions = _create_regions_from_segments(segments)

        # Step 5: Extract keywords
        keywords = _extract_keywords(full_text)

        logger.info(
            f"Transcript extraction complete: {len(full_text)} chars, "
            f"{len(enriched_regions)} regions, {len(keywords)} keywords"
        )

        return TranscriptResult(
            full_text=full_text,
            regions=enriched_regions,
            keywords=keywords,
        )

    except Exception as e:
        logger.error(f"Transcript extraction failed: {e}")
        return TranscriptResult(regions=list(speech_regions))

    finally:
        # Step 6: Clean up temp audio file
        if os.path.exists(tmp_audio_path):
            try:
                os.remove(tmp_audio_path)
                logger.info("Cleaned up temp audio file")
            except OSError as e:
                logger.warning(f"Failed to clean up temp audio: {e}")


# ── Mock extractor ───────────────────────────────────────────────

async def extract_transcript_mock(
    video_path: str,
    speech_regions: List[SpeechRegion],
) -> TranscriptResult:
    """
    Mock transcript extractor that returns placeholder text.

    Useful for testing or when skipping the actual Whisper model.
    Generates placeholder transcript text based on speech region timings.
    """
    logger.info(f"Mock transcript extraction for {video_path}")

    if not speech_regions:
        return TranscriptResult(
            full_text="[Mock transcript — no speech regions provided]",
            regions=[],
            keywords=["mock", "transcript", "placeholder"],
        )

    mock_regions: List[SpeechRegion] = []
    text_parts: List[str] = []

    for idx, region in enumerate(speech_regions):
        duration = region.end - region.start
        placeholder = (
            f"[Speech region {idx + 1}: {region.start:.1f}s - {region.end:.1f}s, "
            f"duration {duration:.1f}s]"
        )
        text_parts.append(placeholder)
        mock_regions.append(SpeechRegion(
            start=region.start,
            end=region.end,
            transcript=placeholder,
            keywords=region.keywords,
        ))

    full_text = " ".join(text_parts)

    return TranscriptResult(
        full_text=full_text,
        regions=mock_regions,
        keywords=["mock", "transcript", "placeholder"],
    )
