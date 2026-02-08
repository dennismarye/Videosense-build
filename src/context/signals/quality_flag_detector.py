"""
Quality Flag Detector — detects specific quality issues in videos.

Analyzes video for common quality problems:
- Static intros (no scene changes early on)
- Low audio energy
- Dark frames
- Excessive silence
- Abrupt endings

Deterministic: same video → same flags every time.
"""

import logging
import os
import subprocess
import tempfile
from typing import List, Optional

from PIL import Image

from src.context.models import AudioTone, QualityFlag, Scene, TimeRange

logger = logging.getLogger(__name__)

# ── Configurable thresholds ──────────────────────────────────

# Static intro: max seconds before first scene change
STATIC_INTRO_THRESHOLD_S = 10.0

# Low audio: energy below this is flagged
LOW_AUDIO_ENERGY_THRESHOLD = 0.2

# Dark frame: mean brightness below this (out of 255) is flagged
DARK_FRAME_BRIGHTNESS_THRESHOLD = 40

# Frame sampling: extract one frame every N seconds for dark frame check
DARK_FRAME_SAMPLE_INTERVAL_S = 10.0

# Excessive silence: ratio of silence to total duration
EXCESSIVE_SILENCE_RATIO = 0.4

# Abrupt ending: speech within N seconds of video end
ABRUPT_ENDING_GAP_S = 1.0


def detect_quality_flags(
    video_path: str,
    duration: float,
    scenes: List[Scene],
    audio_tone: Optional[AudioTone],
    silence_regions: List[TimeRange],
) -> List[QualityFlag]:
    """
    Detect quality issues in a video.

    Runs all quality checks and returns a sorted list of QualityFlag objects.
    Each check is independent — a failure in one does not block others.
    """
    flags: List[QualityFlag] = []

    flags.extend(_check_static_intro(scenes, duration))
    flags.extend(_check_low_audio(audio_tone))
    flags.extend(_check_dark_frames(video_path, duration))
    flags.extend(_check_excessive_silence(silence_regions, duration))
    flags.extend(_check_abrupt_ending(silence_regions, duration))

    # Sort by timestamp (stable sort preserves insertion order for ties)
    flags.sort(key=lambda f: f.timestamp)

    logger.info(f"Detected {len(flags)} quality flags for {video_path}")
    return flags


# ── Individual detectors ─────────────────────────────────────


def _check_static_intro(
    scenes: List[Scene],
    duration: float,
    threshold_s: float = STATIC_INTRO_THRESHOLD_S,
) -> List[QualityFlag]:
    """
    Detect a static intro — no scene change in the first N seconds.

    If the first scene boundary is beyond the threshold, flag it.
    Severity scales linearly: 10s → 0.3, 20s → 0.6, 30s+ → 0.9.
    """
    if duration <= 0:
        return []

    # Find the first scene boundary timestamp
    if not scenes:
        # No scenes detected at all — the entire video is one scene
        first_boundary = duration
    else:
        # The first scene's end is the first boundary
        first_boundary = scenes[0].end if scenes[0].end > 0 else duration

    if first_boundary <= threshold_s:
        return []

    # Severity: linear from 0.3 at threshold to 0.9 at 3x threshold
    severity = min(0.9, 0.3 * (first_boundary / threshold_s))
    severity = round(severity, 2)

    flag = QualityFlag(type="static_intro", timestamp=0.0, severity=severity)
    logger.info(f"Quality flag: static_intro — first scene change at {first_boundary:.1f}s (severity={severity})")
    return [flag]


def _check_low_audio(
    audio_tone: Optional[AudioTone],
    threshold: float = LOW_AUDIO_ENERGY_THRESHOLD,
) -> List[QualityFlag]:
    """
    Detect low audio energy.

    If audio energy is below the threshold, flag the entire video.
    Severity is inversely proportional to energy.
    """
    if audio_tone is None:
        return []

    if audio_tone.energy >= threshold:
        return []

    # Severity: lower energy → higher severity
    # energy 0.0 → severity 1.0, energy threshold → severity ~0.0
    if audio_tone.energy <= 0:
        severity = 1.0
    else:
        severity = min(1.0, 1.0 - (audio_tone.energy / threshold))
    severity = round(severity, 2)

    flag = QualityFlag(type="low_audio", timestamp=0.0, severity=severity)
    logger.info(f"Quality flag: low_audio — energy={audio_tone.energy} (severity={severity})")
    return [flag]


def _check_dark_frames(
    video_path: str,
    duration: float,
    sample_interval: float = DARK_FRAME_SAMPLE_INTERVAL_S,
    brightness_threshold: int = DARK_FRAME_BRIGHTNESS_THRESHOLD,
) -> List[QualityFlag]:
    """
    Detect dark frames by sampling one frame per interval.

    Extracts frames via FFmpeg, analyzes mean brightness with PIL.
    Frames below the brightness threshold are flagged.
    """
    if duration <= 0:
        return []

    flags: List[QualityFlag] = []
    tmp_dir = None

    try:
        tmp_dir = tempfile.mkdtemp(prefix="vs_quality_")

        # Generate sample timestamps
        timestamps = []
        ts = 0.0
        while ts < duration:
            timestamps.append(ts)
            ts += sample_interval

        for sample_ts in timestamps:
            frame_path = os.path.join(tmp_dir, f"frame_{sample_ts:.2f}.jpg")

            try:
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-ss", str(sample_ts),
                    "-i", video_path,
                    "-frames:v", "1",
                    "-q:v", "2",
                    frame_path,
                ]

                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=15,
                )

                if result.returncode != 0 or not os.path.exists(frame_path):
                    continue

                # Analyze brightness with PIL
                brightness = _compute_mean_brightness(frame_path)
                if brightness is None:
                    continue

                if brightness < brightness_threshold:
                    # Severity: inversely proportional to brightness
                    # brightness 0 → 1.0, brightness threshold → ~0.0
                    severity = min(1.0, 1.0 - (brightness / brightness_threshold))
                    severity = round(severity, 2)

                    flag = QualityFlag(
                        type="dark_frame",
                        timestamp=sample_ts,
                        severity=severity,
                    )
                    flags.append(flag)
                    logger.info(
                        f"Quality flag: dark_frame at {sample_ts:.1f}s — "
                        f"brightness={brightness:.1f}/255 (severity={severity})"
                    )

            except subprocess.TimeoutExpired:
                logger.debug(f"Frame extraction timed out at {sample_ts:.1f}s")
            except Exception as e:
                logger.debug(f"Frame analysis failed at {sample_ts:.1f}s: {e}")

    except Exception as e:
        logger.error(f"Dark frame detection failed: {e}")
    finally:
        # Clean up temp directory
        if tmp_dir and os.path.exists(tmp_dir):
            try:
                for f in os.listdir(tmp_dir):
                    os.remove(os.path.join(tmp_dir, f))
                os.rmdir(tmp_dir)
            except OSError:
                pass

    return flags


def _compute_mean_brightness(frame_path: str) -> Optional[float]:
    """
    Compute mean brightness of a frame image.

    Converts to grayscale and returns mean pixel value (0-255).
    """
    try:
        with Image.open(frame_path) as img:
            grayscale = img.convert("L")
            pixels = list(grayscale.getdata())
            if not pixels:
                return None
            return sum(pixels) / len(pixels)
    except Exception as e:
        logger.debug(f"Brightness computation failed for {frame_path}: {e}")
        return None


def _check_excessive_silence(
    silence_regions: List[TimeRange],
    duration: float,
    ratio_threshold: float = EXCESSIVE_SILENCE_RATIO,
) -> List[QualityFlag]:
    """
    Detect excessive silence — more than 40% of the video is silent.

    Severity is proportional to the silence ratio.
    """
    if duration <= 0:
        return []

    total_silence = sum(r.end - r.start for r in silence_regions)
    ratio = min(total_silence / duration, 1.0)

    if ratio <= ratio_threshold:
        return []

    severity = round(min(ratio, 1.0), 2)

    flag = QualityFlag(type="excessive_silence", timestamp=0.0, severity=severity)
    logger.info(f"Quality flag: excessive_silence — {ratio:.1%} silent (severity={severity})")
    return [flag]


def _check_abrupt_ending(
    silence_regions: List[TimeRange],
    duration: float,
    gap_threshold: float = ABRUPT_ENDING_GAP_S,
) -> List[QualityFlag]:
    """
    Detect abrupt endings — video ends mid-speech or mid-scene.

    If the last non-silent (speech) region ends within gap_threshold of
    the video's end, it suggests the video was cut off.
    """
    if duration <= 0 or not silence_regions:
        return []

    # Derive speech regions by inverting silence
    # Find the end of the last speech region
    # Speech exists in the gaps between silence regions and at the boundaries
    sorted_silence = sorted(silence_regions, key=lambda r: r.start)

    # The last silence region's end tells us where the last speech starts
    last_silence_end = sorted_silence[-1].end

    if last_silence_end >= duration:
        # Video ends in silence — not abrupt
        return []

    # Speech continues from after last silence to end of video
    last_speech_end = duration
    speech_gap_to_end = duration - last_silence_end

    # If this final speech segment is very short and runs right up to the end,
    # it suggests the video was cut off mid-speech
    if speech_gap_to_end <= gap_threshold and speech_gap_to_end > 0:
        flag = QualityFlag(
            type="abrupt_ending",
            timestamp=duration,
            severity=0.5,
        )
        logger.info(
            f"Quality flag: abrupt_ending — speech ends {speech_gap_to_end:.2f}s "
            f"before video end (severity=0.5)"
        )
        return [flag]

    return []
