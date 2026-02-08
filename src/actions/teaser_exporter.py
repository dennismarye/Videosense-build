"""
Teaser Exporter — render PlatformBundles to video files via FFmpeg.

Takes a list of PlatformBundle objects (already packaged with platform-specific
duration caps, aspect ratios, and metadata) and exports each one as an MP4
file. Each export applies the correct crop/scale filter for the target format
and optionally composites a watermark overlay.

Uses asyncio subprocess execution with a semaphore to control the number
of concurrent FFmpeg processes, matching the pattern in clip_operations.

Usage:
    bundles = await export_teasers(bundles, teasers, source, output_dir)
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict, List, Optional

from src.context.models import ClipFormat, Platform, PlatformBundle, Teaser

logger = logging.getLogger(__name__)


# ── Platform label mapping ─────────────────────────────────

_PLATFORM_LABELS: Dict[str, str] = {
    "circo": "circo",
    "tiktok": "tiktok",
    "instagram_reels": "ig_reels",
    "x": "x",
    "youtube_shorts": "yt_shorts",
}


def _platform_label(platform: Platform) -> str:
    """Return a filesystem-safe label for the platform."""
    return _PLATFORM_LABELS.get(platform.value, platform.value)


# ── Video filter helpers ───────────────────────────────────

def _build_video_filter(fmt: ClipFormat) -> str:
    """
    Build the FFmpeg -vf filter string for the target aspect ratio.

    - PORTRAIT (9:16): center crop to 9:16, then scale to 1080x1920
    - SQUARE (1:1): center crop to square, then scale to 1080x1080
    - LANDSCAPE (16:9): no crop (passthrough), scale to 1920x1080
    """
    if fmt == ClipFormat.PORTRAIT:
        return "crop=ih*9/16:ih,scale=1080:1920"
    elif fmt == ClipFormat.SQUARE:
        return "crop=min(iw\\,ih):min(iw\\,ih),scale=1080:1080"
    else:
        return "scale=1920:1080"


def _apply_watermark_overlay(base_vf: str, watermark_path: str) -> str:
    """
    Build a filter_complex string that applies the base video filter
    and then composites a watermark in the bottom-right corner.

    The watermark is offset 10px from the right and bottom edges.
    """
    return (
        f"[0:v]{base_vf}[scaled];"
        f"[scaled][1:v]overlay=W-w-10:H-h-10[out]"
    )


# ── FFmpeg command builder ─────────────────────────────────

def _build_teaser_ffmpeg_cmd(
    teaser: Teaser,
    bundle: PlatformBundle,
    source_path: str,
    output_path: str,
    watermark_path: Optional[str],
) -> List[str]:
    """
    Build a complete FFmpeg command to export a single teaser bundle.

    When watermarking is enabled (bundle.watermarked=True and a valid
    watermark_path is supplied), uses -filter_complex with a second
    input and -map for the composited output. Otherwise uses simple -vf.

    Args:
        teaser: The Teaser providing the source time range.
        bundle: The PlatformBundle with format, duration, and flags.
        source_path: Path to the source video file.
        output_path: Destination path for the exported file.
        watermark_path: Optional path to a watermark image file.

    Returns:
        FFmpeg command as a list of strings for subprocess execution.
    """
    base_vf = _build_video_filter(bundle.format)
    use_watermark = (
        bundle.watermarked
        and watermark_path is not None
        and os.path.isfile(watermark_path)
    )

    cmd = [
        "ffmpeg",
        "-y",                           # overwrite output
        "-ss", str(teaser.start),       # seek to start (before -i for fast seek)
        "-i", source_path,              # primary input
    ]

    if use_watermark:
        cmd.extend(["-i", watermark_path])  # second input: watermark image

    cmd.extend([
        "-t", str(bundle.duration),     # duration to extract
    ])

    if use_watermark:
        filter_complex = _apply_watermark_overlay(base_vf, watermark_path)
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[out]",
            "-map", "0:a?",
        ])
    else:
        cmd.extend(["-vf", base_vf])

    cmd.extend([
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "copy",
        output_path,
    ])

    logger.debug(
        f"FFmpeg cmd for bundle {bundle.bundle_id} "
        f"({bundle.format.value}, {_platform_label(bundle.platform)}): "
        f"{' '.join(cmd)}"
    )
    return cmd


# ── Single bundle export ───────────────────────────────────

async def _export_single_bundle(
    bundle: PlatformBundle,
    teaser: Teaser,
    source_path: str,
    output_dir: str,
    watermark_path: Optional[str],
) -> PlatformBundle:
    """
    Export a single PlatformBundle to an MP4 file using FFmpeg.

    Updates the bundle in-place with output_path and exported=True on
    success, or sets the error field on failure.

    Args:
        bundle: The PlatformBundle to export.
        teaser: The corresponding Teaser with source time range.
        source_path: Path to the source video file.
        output_dir: Directory to write the output file.
        watermark_path: Optional path to watermark image.

    Returns:
        The updated PlatformBundle.
    """
    label = _platform_label(bundle.platform)
    filename = f"{bundle.bundle_id}_{label}.mp4"
    output_path = os.path.join(output_dir, filename)

    cmd = _build_teaser_ffmpeg_cmd(
        teaser, bundle, source_path, output_path, watermark_path,
    )

    logger.info(
        f"Exporting bundle {bundle.bundle_id} "
        f"({label}, {bundle.format.value}) "
        f"[{teaser.start:.2f}s - {teaser.end:.2f}s, "
        f"dur={bundle.duration:.2f}s] -> {output_path}"
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
            logger.error(f"Bundle {bundle.bundle_id} export failed: {error_msg}")
            bundle.error = error_msg
            return bundle

        # Verify output file was created
        if not os.path.exists(output_path):
            error_msg = f"FFmpeg completed but output file not found: {output_path}"
            logger.error(error_msg)
            bundle.error = error_msg
            return bundle

        bundle.output_path = output_path
        bundle.exported = True
        logger.info(
            f"Bundle {bundle.bundle_id} exported successfully: "
            f"{os.path.getsize(output_path)} bytes"
        )

    except FileNotFoundError:
        error_msg = (
            "FFmpeg not found. Ensure FFmpeg is installed and available on PATH."
        )
        logger.error(error_msg)
        bundle.error = error_msg

    except Exception as e:
        error_msg = f"Unexpected error exporting bundle {bundle.bundle_id}: {e}"
        logger.error(error_msg, exc_info=True)
        bundle.error = error_msg

    return bundle


# ── Public API ─────────────────────────────────────────────

async def export_teasers(
    bundles: List[PlatformBundle],
    teasers: List[Teaser],
    source_path: str,
    output_dir: str,
    watermark_path: Optional[str] = None,
    max_concurrent: int = 3,
) -> List[PlatformBundle]:
    """
    Export all PlatformBundles as video files with controlled concurrency.

    Matches each bundle to its source teaser, builds and runs an FFmpeg
    command per bundle, and updates each bundle's output_path / exported /
    error fields. An asyncio.Semaphore limits the number of simultaneous
    FFmpeg processes to avoid CPU and I/O saturation.

    Args:
        bundles: List of PlatformBundle objects to export.
        teasers: List of Teaser objects (looked up by teaser_id).
        source_path: Path to the source video file.
        output_dir: Directory to write exported files into.
        watermark_path: Optional path to a watermark image. Only applied
                        to bundles where watermarked=True.
        max_concurrent: Maximum number of FFmpeg processes running at
                        the same time. Defaults to 3.

    Returns:
        The same bundles list with output_path, exported, and error
        fields updated.
    """
    if not bundles:
        logger.info("No bundles to export; returning empty results")
        return []

    # Build teaser lookup
    teaser_map: Dict[str, Teaser] = {t.teaser_id: t for t in teasers}

    # Ensure output directory exists
    try:
        os.makedirs(output_dir, exist_ok=True)
    except OSError as e:
        error_msg = f"Failed to create output directory {output_dir}: {e}"
        logger.error(error_msg)
        for bundle in bundles:
            bundle.error = error_msg
        return bundles

    logger.info(
        f"Exporting {len(bundles)} teaser bundles from {source_path} "
        f"(max_concurrent={max_concurrent})"
    )

    semaphore = asyncio.Semaphore(max_concurrent)

    async def _bounded_export(bundle: PlatformBundle) -> PlatformBundle:
        # Resolve the teaser for this bundle
        teaser = teaser_map.get(bundle.teaser_id)
        if teaser is None:
            error_msg = (
                f"No teaser found for teaser_id={bundle.teaser_id} "
                f"in bundle {bundle.bundle_id}"
            )
            logger.error(error_msg)
            bundle.error = error_msg
            return bundle

        async with semaphore:
            return await _export_single_bundle(
                bundle, teaser, source_path, output_dir, watermark_path,
            )

    # Launch all tasks; semaphore gates actual concurrency
    tasks = [_bounded_export(bundle) for bundle in bundles]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Convert any unexpected exceptions into error bundles
    processed: List[PlatformBundle] = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            bundle = bundles[i]
            error_msg = f"Task exception for bundle {bundle.bundle_id}: {result}"
            logger.error(error_msg, exc_info=result)
            bundle.error = error_msg
            processed.append(bundle)
        else:
            processed.append(result)

    succeeded = sum(1 for b in processed if b.exported)
    failed = len(processed) - succeeded
    logger.info(
        f"Teaser export complete: {succeeded} succeeded, {failed} failed "
        f"out of {len(processed)} total"
    )

    return processed
