"""
Local video analyzer — reads videos from the local filesystem instead of S3.

Wraps ffprobe to provide the same interface as S3VideoAnalyzer but without
any AWS credentials or network calls.
"""

import logging
import os
from typing import Dict, Any, Optional, Tuple
from urllib.parse import urlparse

import ffmpeg

logger = logging.getLogger(__name__)


class LocalVideoAnalyzer:
    """
    Drop-in replacement for S3VideoAnalyzer that works with local files.

    Accepts both local file paths and URLs — for URLs it just passes them
    through to ffprobe (works for public URLs and local file:// URIs).
    """

    def __init__(self, local_input_dir: str = "local_storage/input"):
        self.local_input_dir = local_input_dir
        os.makedirs(self.local_input_dir, exist_ok=True)
        self.s3_client = None  # No S3 client in local mode
        self.logger = logger
        logger.info(f"LocalVideoAnalyzer initialized (input dir: {local_input_dir})")

    def _resolve_path(self, path_or_url: str) -> str:
        """
        Resolve a video path. Handles:
        - Absolute local paths (/path/to/file.mp4)
        - Relative paths (file.mp4 → looks in local_input_dir)
        - file:// URLs
        - S3-style URLs (maps to local_input_dir by filename)
        """
        if os.path.isabs(path_or_url) and os.path.exists(path_or_url):
            return path_or_url

        if path_or_url.startswith("file://"):
            return path_or_url.replace("file://", "")

        # If it looks like an S3/HTTP URL, extract the filename and look locally
        if "://" in path_or_url:
            parsed = urlparse(path_or_url)
            filename = os.path.basename(parsed.path)
            local_path = os.path.join(self.local_input_dir, filename)
            if os.path.exists(local_path):
                logger.info(f"Resolved URL to local file: {local_path}")
                return local_path
            # Fall through — let ffprobe try the URL directly
            return path_or_url

        # Relative path — check input dir
        local_path = os.path.join(self.local_input_dir, path_or_url)
        if os.path.exists(local_path):
            return local_path

        return path_or_url

    def _get_presigned_url(self, url: str) -> str:
        """In local mode, just resolve to a local path."""
        return self._resolve_path(url)

    def _parse_s3_url(self, s3_url: str) -> Optional[Tuple[str, str]]:
        """Not used in local mode, but kept for interface compatibility."""
        return None

    def detect_video_quality(self, width: int, height: int) -> str:
        if width == 0 or height == 0:
            return "Unknown"
        short_side = min(width, height)
        if short_side >= 2160:
            return "4K"
        elif short_side >= 1440:
            return "1440p"
        elif short_side >= 1080:
            return "1080p"
        elif short_side >= 720:
            return "720p"
        elif short_side >= 480:
            return "480p"
        elif short_side >= 360:
            return "360p"
        elif short_side >= 240:
            return "240p"
        elif short_side >= 144:
            return "144p"
        else:
            return "Sub-144p"

    def check_audio_presence(self, detailed_info: Dict[str, Any]) -> Dict[str, Any]:
        if not detailed_info:
            return {"has_audio": False, "audio_details": "Unable to analyze"}
        audio_info = detailed_info.get("audio")
        if audio_info:
            channels = audio_info.get("channels", 0)
            sample_rate = audio_info.get("sample_rate", 0)
            codec = audio_info.get("codec", "")
            has_valid_audio = channels > 0 and sample_rate > 0 and codec != ""
            return {
                "has_audio": has_valid_audio,
                "audio_details": (
                    {
                        "codec": codec,
                        "channels": channels,
                        "sample_rate": sample_rate,
                        "channel_layout": audio_info.get("channel_layout", ""),
                        "bitrate_kbps": (
                            round(audio_info.get("bit_rate", 0) / 1000, 1)
                            if audio_info.get("bit_rate")
                            else 0
                        ),
                    }
                    if has_valid_audio
                    else "No valid audio stream"
                ),
            }
        return {"has_audio": False, "audio_details": "No audio stream found"}

    def get_basic_info(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            resolved = self._resolve_path(path)
            probe = ffmpeg.probe(resolved, v="error")
            return probe
        except ffmpeg.Error as e:
            self.logger.error(f"FFmpeg error probing {path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error probing {path}: {e}")
            return None

    def get_detailed_info(self, path: str) -> Optional[Dict[str, Any]]:
        try:
            resolved = self._resolve_path(path)
            probe = ffmpeg.probe(resolved, v="error")

            format_info = probe.get("format", {})
            streams = probe.get("streams", [])
            video_stream = next(
                (s for s in streams if s.get("codec_type") == "video"), None
            )
            audio_stream = next(
                (s for s in streams if s.get("codec_type") == "audio"), None
            )

            result = {
                "file_info": {
                    "filename": format_info.get("filename", ""),
                    "format_name": format_info.get("format_name", ""),
                    "duration": float(format_info.get("duration", 0)),
                    "size_bytes": int(format_info.get("size", 0)),
                    "bit_rate": (
                        int(format_info.get("bit_rate", 0))
                        if format_info.get("bit_rate")
                        else 0
                    ),
                }
            }

            if video_stream:
                fps_str = video_stream.get("r_frame_rate", "0/1")
                try:
                    num, den = map(int, fps_str.split("/"))
                    fps = num / den if den != 0 else 0
                except ValueError:
                    fps = 0

                width = int(video_stream.get("width", 0))
                height = int(video_stream.get("height", 0))
                quality_rating = self.detect_video_quality(width, height)

                result["video"] = {
                    "codec": video_stream.get("codec_name", ""),
                    "width": width,
                    "height": height,
                    "fps": round(fps, 2),
                    "bit_rate": (
                        int(video_stream.get("bit_rate", 0))
                        if video_stream.get("bit_rate")
                        else 0
                    ),
                    "pixel_format": video_stream.get("pix_fmt", ""),
                    "profile": video_stream.get("profile", ""),
                    "level": video_stream.get("level", ""),
                    "quality_rating": quality_rating,
                    "orientation": (
                        "landscape"
                        if width > height
                        else "portrait" if height > width else "square"
                    ),
                    "aspect_ratio": round(width / height, 2) if height > 0 else 0,
                }

            if audio_stream:
                result["audio"] = {
                    "codec": audio_stream.get("codec_name", ""),
                    "sample_rate": int(audio_stream.get("sample_rate", 0)),
                    "channels": int(audio_stream.get("channels", 0)),
                    "bit_rate": (
                        int(audio_stream.get("bit_rate", 0))
                        if audio_stream.get("bit_rate")
                        else 0
                    ),
                    "channel_layout": audio_stream.get("channel_layout", ""),
                }

            audio_analysis = self.check_audio_presence(result)
            result["audio_analysis"] = audio_analysis
            result["quality_assessment"] = self._assess_quality(result)

            return result

        except ffmpeg.Error as e:
            self.logger.error(f"FFmpeg error getting detailed info for {path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting detailed info for {path}: {e}")
            return None

    def _assess_quality(self, detailed_info: Dict[str, Any]) -> Dict[str, Any]:
        """Simplified quality assessment (same logic as S3VideoAnalyzer)."""
        video_info = detailed_info.get("video", {})
        audio_analysis = detailed_info.get("audio_analysis", {})
        score = 0

        quality_rating = video_info.get("quality_rating", "Unknown")
        resolution_scores = {
            "4K": 25, "1440p": 22, "1080p": 20, "720p": 15,
            "480p": 10, "360p": 6, "240p": 3, "144p": 1,
        }
        score += resolution_scores.get(quality_rating, 0)

        fps = video_info.get("fps", 0)
        if fps >= 60:
            score += 20
        elif fps >= 30:
            score += 15
        elif fps >= 24:
            score += 10
        elif fps >= 15:
            score += 5

        if audio_analysis.get("has_audio", False):
            score += 15
            audio_details = audio_analysis.get("audio_details", {})
            if isinstance(audio_details, dict) and audio_details.get("channels", 0) >= 2:
                score += 5

        codec = video_info.get("codec", "").lower()
        if "h265" in codec or "hevc" in codec:
            score += 15
        elif "h264" in codec:
            score += 12
        elif "vp9" in codec:
            score += 10
        elif codec:
            score += 5

        level = "EXCELLENT" if score >= 80 else "GOOD" if score >= 65 else "FAIR" if score >= 45 else "POOR"

        return {
            "overall_score": min(score, 100),
            "quality_level": level,
            "recommendations": [],
        }

    def validate_video_file(self, path: str) -> Dict[str, Any]:
        resolved = self._resolve_path(path)
        if not os.path.exists(resolved):
            return {"is_valid": False, "error": f"File not found: {resolved}"}
        basic_info = self.get_basic_info(resolved)
        if not basic_info:
            return {"is_valid": False, "error": "Cannot read file or file is corrupted"}
        streams = basic_info.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        if not video_streams:
            return {"is_valid": False, "error": "No video streams found in file"}
        return {
            "is_valid": True,
            "video_streams": len(video_streams),
            "audio_streams": len([s for s in streams if s.get("codec_type") == "audio"]),
        }

    def get_video_thumbnail_info(self, path: str) -> Dict[str, Any]:
        detailed_info = self.get_detailed_info(path)
        if not detailed_info:
            return {"error": "Could not analyze video"}
        video_info = detailed_info.get("video", {})
        duration = detailed_info.get("file_info", {}).get("duration", 0)
        return {
            "optimal_thumbnail_time": duration / 2 if duration > 0 else 0,
            "video_duration": duration,
            "resolution": f"{video_info.get('width', 0)}x{video_info.get('height', 0)}",
            "orientation": video_info.get("orientation", "unknown"),
        }
