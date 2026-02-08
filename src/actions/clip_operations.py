"""
Clip Operations — execute clip suggestions via FFmpeg.

Provides async wrappers around FFmpeg to extract individual clips
or process batches with controlled concurrency. Each extraction uses
the filter chain from edl_exporter to handle aspect-ratio cropping
and scaling.

Usage:
    result = await extract_clip(source, clip, output_dir)
    results = await extract_clips_batch(source, clips, output_dir, max_concurrent=3)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import List, Optional

from src.actions.edl_exporter import generate_ffmpeg_extract_cmd
from src.context.models import SuggestedClip

logger = logging.getLogger(__name__)


# ── Format label mapping ────────────────────────────────────

_FORMAT_LABELS = {
    "16:9": "16x9",
    "9:16": "9x16",
    "1:1": "1x1",
}


def _format_label(clip: SuggestedClip) -> str:
    """Return a filesystem-safe label for the clip format."""
    return _FORMAT_LABELS.get(clip.format.value, "16x9")


# ── Single Clip Extraction ──────────────────────────────────

async def extract_clip(
    source_path: str,
    clip: SuggestedClip,
    output_dir: str,
) -> dict:
    """
    Extract a single clip from the source video using FFmpeg.

    Creates the output directory if it doesn't exist. Builds the FFmpeg
    command via generate_ffmpeg_extract_cmd and runs it as an async
    subprocess.

    Args:
        source_path: Path to the source video file.
        clip: SuggestedClip with time range, format, and metadata.
        output_dir: Directory to write the extracted clip into.

    Returns:
        Dict with keys:
          - clip_id (str): The clip's unique identifier.
          - output_path (str): Full path to the output file.
          - format (str): The clip format value (e.g., "16:9").
          - duration (float): Expected clip duration in seconds.
          - success (bool): Whether extraction completed without error.
          - error (Optional[str]): Error message if extraction failed.
    """
    duration = clip.end - clip.start
    label = _format_label(clip)
    filename = f"{clip.clip_id}_{label}.mp4"
    output_path = os.path.join(output_dir, filename)

    result = {
        "clip_id": clip.clip_id,
        "output_path": output_path,
        "format": clip.format.value,
        "duration": duration,
        "success": False,
        "error": None,
    }

    # Ensure output directory exists
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        error_msg = f"Failed to create output directory {output_dir}: {e}"
        logger.error(error_msg)
        result["error"] = error_msg
        return result

    # Build the FFmpeg command
    cmd = generate_ffmpeg_extract_cmd(clip, source_path, output_path)

    logger.info(
        f"Extracting clip {clip.clip_id} ({label}) "
        f"[{clip.start:.2f}s - {clip.end:.2f}s] -> {output_path}"
    )

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()

        if process.returncode != 0:
            error_msg = (
                f"FFmpeg exited with code {process.returncode}: "
                f"{stderr.decode('utf-8', errors='replace').strip()}"
            )
            logger.error(f"Clip {clip.clip_id} extraction failed: {error_msg}")
            result["error"] = error_msg
            return result

        # Verify output file was created
        if not os.path.exists(output_path):
            error_msg = f"FFmpeg completed but output file not found: {output_path}"
            logger.error(error_msg)
            result["error"] = error_msg
            return result

        result["success"] = True
        logger.info(
            f"Clip {clip.clip_id} extracted successfully: "
            f"{os.path.getsize(output_path)} bytes"
        )

    except FileNotFoundError:
        error_msg = (
            "FFmpeg not found. Ensure FFmpeg is installed and available on PATH."
        )
        logger.error(error_msg)
        result["error"] = error_msg

    except Exception as e:
        error_msg = f"Unexpected error extracting clip {clip.clip_id}: {e}"
        logger.error(error_msg, exc_info=True)
        result["error"] = error_msg

    return result


# ── Batch Clip Extraction ───────────────────────────────────

async def extract_clips_batch(
    source_path: str,
    clips: List[SuggestedClip],
    output_dir: str,
    max_concurrent: int = 3,
) -> List[dict]:
    """
    Extract multiple clips with controlled concurrency.

    Uses an asyncio.Semaphore to limit the number of simultaneous FFmpeg
    processes, preventing I/O and CPU overload on the host machine.

    Args:
        source_path: Path to the source video file.
        clips: List of SuggestedClip objects to extract.
        output_dir: Directory to write all extracted clips into.
        max_concurrent: Maximum number of FFmpeg processes running
                        at the same time. Defaults to 3.

    Returns:
        List of result dicts (one per clip), in the same order as
        the input clips list.
    """
    if not clips:
        logger.info("No clips to extract; returning empty results")
        return []

    logger.info(
        f"Batch extracting {len(clips)} clips from {source_path} "
        f"(max_concurrent={max_concurrent})"
    )

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _bounded_extract(clip: SuggestedClip) -> dict:
        async with semaphore:
            return await extract_clip(source_path, clip, output_dir)

    # Launch all tasks; semaphore gates actual concurrency
    tasks = [_bounded_extract(clip) for clip in clips]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert any unexpected exceptions into error dicts
    processed: List[dict] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            clip = clips[i]
            error_msg = f"Task exception for clip {clip.clip_id}: {result}"
            logger.error(error_msg, exc_info=result)
            processed.append({
                "clip_id": clip.clip_id,
                "output_path": os.path.join(
                    output_dir,
                    f"{clip.clip_id}_{_format_label(clip)}.mp4",
                ),
                "format": clip.format.value,
                "duration": clip.end - clip.start,
                "success": False,
                "error": error_msg,
            })
        else:
            processed.append(result)

    succeeded = sum(1 for r in processed if r["success"])
    failed = len(processed) - succeeded
    logger.info(
        f"Batch extraction complete: {succeeded} succeeded, {failed} failed "
        f"out of {len(processed)} total"
    )

    return processed
