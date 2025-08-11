import ffmpeg
import subprocess
import json
import os
import logging
import boto3
from botocore.exceptions import ClientError
from urllib.parse import urlparse
import math
from typing import Dict, Any, Optional, Tuple, List


class S3VideoAnalyzer:
    """Enhanced S3 Video Analyzer for quality assessment and video analysis"""

    def __init__(self, aws_access_key=None, aws_secret_key=None, region="us-east-1"):
        """Initialize the S3 Video Analyzer with optional AWS credentials"""
        """Initialize the S3 Video Analyzer with optional AWS credentials"""
        self.aws_access_key = aws_access_key
        self.aws_secret_key = aws_secret_key
        self.region = region

        if aws_access_key:
            os.environ["AWS_ACCESS_KEY_ID"] = aws_access_key
            os.environ["AWS_SECRET_ACCESS_KEY"] = aws_secret_key
            os.environ["AWS_DEFAULT_REGION"] = region

        # Initialize S3 client for presigned URLs
        try:
            if aws_access_key and aws_secret_key:
                self.s3_client = boto3.client(
                    "s3",
                    aws_access_key_id=aws_access_key,
                    aws_secret_access_key=aws_secret_key,
                    region_name=region,
                )
            else:
                self.s3_client = boto3.client("s3", region_name=region)
        except Exception as e:
            self.s3_client = None
            print(f"Warning: Could not initialize S3 client: {e}")

        self.logger = logging.getLogger(__name__)

    def _parse_s3_url(self, s3_url: str) -> Optional[Tuple[str, str]]:
        """Parse S3 URL to extract bucket and key"""
        try:
            if s3_url.startswith("s3://"):
                # s3://bucket/key format
                parsed = urlparse(s3_url)
                bucket = parsed.netloc
                key = parsed.path.lstrip("/")
                return bucket, key
            elif "s3." in s3_url or "s3-" in s3_url:
                # https://bucket.s3.region.amazonaws.com/key or https://s3.region.amazonaws.com/bucket/key
                parsed = urlparse(s3_url)
                path_parts = parsed.path.strip("/").split("/")

                if parsed.netloc.startswith("s3.") or parsed.netloc.startswith("s3-"):
                    # https://s3.region.amazonaws.com/bucket/key format
                    bucket = path_parts[0]
                    key = "/".join(path_parts[1:]) if len(path_parts) > 1 else ""
                else:
                    # https://bucket.s3.region.amazonaws.com/key format
                    # 🔥 FIX: Extract bucket name properly when it contains dots
                    netloc = parsed.netloc
                    if ".s3." in netloc:
                        bucket = netloc.split(".s3.")[0]  # Get everything before .s3.
                    else:
                        bucket = netloc.split(".")[0]  # Fallback for simple names
                    key = parsed.path.lstrip("/")

                return bucket, key
            return None
        except Exception as e:
            self.logger.error(f"Error parsing S3 URL {s3_url}: {e}")
            return None

    def _get_presigned_url(self, s3_url: str) -> str:
        """Convert S3 URL to presigned URL, or return original if not S3 or no credentials"""
        # If not an S3 URL, return as-is
        if not ("s3." in s3_url or "s3://" in s3_url):
            return s3_url

        # If no S3 client, return original URL (will work for public files)
        if not self.s3_client:
            return s3_url

        try:
            parsed = self._parse_s3_url(s3_url)
            if not parsed:
                return s3_url

            bucket, key = parsed

            # Generate presigned URL (1 hour expiry)
            presigned_url = self.s3_client.generate_presigned_url(
                "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600
            )
            return presigned_url

        except Exception as e:
            self.logger.warning(f"Could not generate presigned URL for {s3_url}: {e}")
            return s3_url  # Fallback to original URL

    def detect_video_quality(self, width: int, height: int) -> str:
        """
        Detect video quality from width and height dimensions.
        Includes all resolutions from 144p to 4K+
        """
        if width == 0 or height == 0:
            return "Unknown"

        # Use the shorter dimension for quality detection (works for both portrait/landscape)
        short_side = min(width, height)

        # Quality detection based on shorter dimension
        if short_side >= 2160:  # 4K
            return "4K"
        elif short_side >= 1440:  # 1440p/2K
            return "1440p"
        elif short_side >= 1080:  # 1080p Full HD
            return "1080p"
        elif short_side >= 720:  # 720p HD
            return "720p"
        elif short_side >= 480:  # 480p SD
            return "480p"
        elif short_side >= 360:  # 360p
            return "360p"
        elif short_side >= 240:  # 240p
            return "240p"
        elif short_side >= 144:  # 144p
            return "144p"
        else:
            return "Sub-144p"  # Very low quality

    def check_audio_presence(self, detailed_info: Dict[str, Any]) -> Dict[str, Any]:
        """
        Check if video has audio based on the analysis
        """
        if not detailed_info:
            return {"has_audio": False, "audio_details": "Unable to analyze"}

        audio_info = detailed_info.get("audio")

        if audio_info:
            # Check if audio stream has valid properties
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
        else:
            return {"has_audio": False, "audio_details": "No audio stream found"}

    def get_basic_info(self, s3_path: str) -> Optional[Dict[str, Any]]:
        """Get basic video information using ffmpeg.probe"""
        try:
            # Use correct ffmpeg-python syntax
            accessible_url = self._get_presigned_url(s3_path)
            probe = ffmpeg.probe(accessible_url, v="error")
            return probe
        except ffmpeg.Error as e:
            self.logger.error(f"FFmpeg error probing {s3_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error probing {s3_path}: {e}")
            return None

    def get_detailed_info(self, s3_path: str) -> Optional[Dict[str, Any]]:
        """Get detailed video information with proper parsing"""
        try:
            accessible_url = self._get_presigned_url(s3_path)
            probe = ffmpeg.probe(accessible_url, v="error")

            # Extract and organize information
            format_info = probe.get("format", {})
            streams = probe.get("streams", [])

            # Find video and audio streams
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
                # Parse frame rate properly
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
                    # Add quality detection
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

            # Add audio presence analysis
            audio_analysis = self.check_audio_presence(result)
            result["audio_analysis"] = audio_analysis

            # Add overall quality assessment
            result["quality_assessment"] = self.assess_overall_quality(result)

            return result

        except ffmpeg.Error as e:
            self.logger.error(f"FFmpeg error getting detailed info for {s3_path}: {e}")
            return None
        except Exception as e:
            self.logger.error(f"Error getting detailed info for {s3_path}: {e}")
            return None

    def assess_overall_quality(self, detailed_info: Dict[str, Any]) -> Dict[str, Any]:
        """Assess overall video quality and provide recommendations"""
        try:
            video_info = detailed_info.get("video", {})
            audio_analysis = detailed_info.get("audio_analysis", {})
            file_info = detailed_info.get("file_info", {})

            # Initialize quality metrics with proper types
            quality_metrics: Dict[str, Any] = {
                "resolution_score": 0,
                "fps_score": 0,
                "audio_score": 0,
                "codec_score": 0,
                "bitrate_score": 0,
                "overall_score": 0,
                "quality_level": "POOR",
                "recommendations": [],  # This will be List[str]
            }

            # Resolution scoring (0-25 points)
            quality_rating = video_info.get(
                "quality_rating", "Unknown"
            )  # Fixed: use quality_rating
            resolution_scores = {
                "4K": 25,
                "1440p": 22,
                "1080p": 20,
                "720p": 15,
                "480p": 10,
                "360p": 6,
                "240p": 3,
                "144p": 1,
            }
            quality_metrics["resolution_score"] = resolution_scores.get(
                quality_rating, 0
            )

            recommendations: List[str] = quality_metrics[
                "recommendations"
            ]  # Type assertion
            if quality_metrics["resolution_score"] < 15:
                recommendations.append("Consider upgrading to at least 720p resolution")

            # FPS scoring (0-20 points)
            fps = video_info.get("fps", 0)
            if fps >= 60:
                quality_metrics["fps_score"] = 20
            elif fps >= 30:
                quality_metrics["fps_score"] = 15
            elif fps >= 24:
                quality_metrics["fps_score"] = 10
            elif fps >= 15:
                quality_metrics["fps_score"] = 5
            else:
                quality_metrics["fps_score"] = 0
                recommendations.append("Frame rate is too low, consider 24fps minimum")

            # Audio scoring (0-20 points)
            if audio_analysis.get("has_audio", False):
                quality_metrics["audio_score"] = 15
                audio_details = audio_analysis.get("audio_details", {})
                if isinstance(audio_details, dict):
                    channels = audio_details.get("channels", 0)
                    if channels >= 2:
                        quality_metrics["audio_score"] += 5
            else:
                recommendations.append(
                    "No audio detected - consider adding audio track"
                )

            # Codec scoring (0-15 points)
            codec = video_info.get("codec", "").lower()
            if "h265" in codec or "hevc" in codec:
                quality_metrics["codec_score"] = 15
            elif "h264" in codec:
                quality_metrics["codec_score"] = 12
            elif "vp9" in codec:
                quality_metrics["codec_score"] = 10
            elif codec:
                quality_metrics["codec_score"] = 5
            else:
                recommendations.append("Unknown or outdated codec detected")

            # Bitrate scoring (0-20 points)
            bitrate = video_info.get("bit_rate", 0)
            width = video_info.get("width", 0)
            height = video_info.get("height", 0)
            duration = file_info.get("duration", 0)

            if width > 0 and height > 0 and bitrate > 0:
                # Calculate bitrate efficiency
                pixels = width * height
                bitrate_per_pixel = bitrate / pixels

                # Optimal bitrate ranges per quality level
                optimal_ranges = {
                    "4K": (0.2, 0.8),
                    "1440p": (0.15, 0.6),
                    "1080p": (0.1, 0.4),
                    "720p": (0.08, 0.3),
                    "480p": (0.06, 0.2),
                }

                if quality_rating in optimal_ranges:
                    min_rate, max_rate = optimal_ranges[quality_rating]
                    if min_rate <= bitrate_per_pixel <= max_rate:
                        quality_metrics["bitrate_score"] = 20
                    elif bitrate_per_pixel < min_rate:
                        quality_metrics["bitrate_score"] = 10
                        recommendations.append(
                            "Bitrate may be too low for optimal quality"
                        )
                    else:
                        quality_metrics["bitrate_score"] = 15
                        recommendations.append("Bitrate may be higher than necessary")
                else:
                    quality_metrics["bitrate_score"] = 10

            # Calculate overall score
            total_score = (
                quality_metrics["resolution_score"]
                + quality_metrics["fps_score"]
                + quality_metrics["audio_score"]
                + quality_metrics["codec_score"]
                + quality_metrics["bitrate_score"]
            )

            quality_metrics["overall_score"] = total_score

            # Determine quality level
            if total_score >= 80:
                quality_metrics["quality_level"] = "EXCELLENT"
            elif total_score >= 65:
                quality_metrics["quality_level"] = "GOOD"
            elif total_score >= 45:
                quality_metrics["quality_level"] = "FAIR"
            else:
                quality_metrics["quality_level"] = "POOR"

            # Add file size recommendations
            file_size_mb = file_info.get("size_bytes", 0) / (1024 * 1024)
            if duration > 0:
                mbps = (file_size_mb * 8) / duration  # Megabits per second
                if mbps > 50:
                    recommendations.append(
                        "File size is very large - consider compression"
                    )
                elif mbps < 1:
                    recommendations.append("File may be over-compressed")

            return quality_metrics

        except Exception as e:
            self.logger.error(f"Error in quality assessment: {e}")
            return {
                "overall_score": 0,
                "quality_level": "POOR",
                "error": str(e),
                "recommendations": ["Quality assessment failed"],
            }

    def get_video_thumbnail_info(self, s3_path: str) -> Dict[str, Any]:
        """Extract thumbnail information from video"""
        try:
            # Get video information
            detailed_info = self.get_detailed_info(s3_path)
            if not detailed_info:
                return {"error": "Could not analyze video for thumbnail"}

            video_info = detailed_info.get("video", {})
            duration = detailed_info.get("file_info", {}).get("duration", 0)

            # Calculate optimal thumbnail extraction time (middle of video)
            thumbnail_time = duration / 2 if duration > 0 else 0

            return {
                "optimal_thumbnail_time": thumbnail_time,
                "video_duration": duration,
                "resolution": f"{video_info.get('width', 0)}x{video_info.get('height', 0)}",
                "orientation": video_info.get("orientation", "unknown"),
            }

        except Exception as e:
            self.logger.error(f"Error getting thumbnail info: {e}")
            return {"error": str(e)}

    def validate_video_file(self, s3_path: str) -> Dict[str, Any]:
        """Validate if the file is a proper video file"""
        try:
            basic_info = self.get_basic_info(s3_path)
            if not basic_info:
                return {
                    "is_valid": False,
                    "error": "Cannot read file or file is corrupted",
                }

            # Check if file has video streams
            streams = basic_info.get("streams", [])
            video_streams = [s for s in streams if s.get("codec_type") == "video"]

            if not video_streams:
                return {"is_valid": False, "error": "No video streams found in file"}

            # Check basic video properties
            video_stream = video_streams[0]
            width = video_stream.get("width", 0)
            height = video_stream.get("height", 0)

            if width <= 0 or height <= 0:
                return {"is_valid": False, "error": "Invalid video dimensions"}

            return {
                "is_valid": True,
                "video_streams": len(video_streams),
                "audio_streams": len(
                    [s for s in streams if s.get("codec_type") == "audio"]
                ),
                "container_format": basic_info.get("format", {}).get(
                    "format_name", "unknown"
                ),
            }

        except Exception as e:
            self.logger.error(f"Error validating video file: {e}")
            return {"is_valid": False, "error": str(e)}


def main():
    """Test the enhanced analyzer"""
    # Initialize analyzer
    analyzer = S3VideoAnalyzer()

    # Your S3 path
    s3_path = "https://s3.eu-west-2.amazonaws.com/staging.circleandclique.org/original-files/2d1ce818-376c-40c2-a69c-6c379788bcb3.mp4"
    print("🎬 Enhanced S3 Video Analysis")
    print("=" * 50)

    # Test validation
    print("\n✅ Video Validation:")
    validation = analyzer.validate_video_file(s3_path)
    print(json.dumps(validation, indent=2))

    # Test basic info
    print("\n📊 Basic Info:")
    basic_info = analyzer.get_basic_info(s3_path)
    if basic_info:
        format_info = basic_info.get("format", {})
        print(f"Duration: {format_info.get('duration', 'unknown')} seconds")
        print(f"Size: {int(format_info.get('size', 0)) / (1024*1024):.2f} MB")
        print(f"Format: {format_info.get('format_name', 'unknown')}")

    # Test detailed info
    print("\n📋 Detailed Analysis:")
    detailed_info = analyzer.get_detailed_info(s3_path)
    if detailed_info:
        print(json.dumps(detailed_info, indent=2))

        # Show quality assessment clearly
        quality_assessment = detailed_info.get("quality_assessment", {})
        print(
            f"\n🎯 Overall Quality: {quality_assessment.get('quality_level', 'Unknown')} "
            f"(Score: {quality_assessment.get('overall_score', 0)}/100)"
        )

        recommendations = quality_assessment.get("recommendations", [])
        if recommendations:
            print("📝 Recommendations:")
            for rec in recommendations:
                print(f"   • {rec}")

    # Test thumbnail info
    print("\n🖼️ Thumbnail Info:")
    thumbnail_info = analyzer.get_video_thumbnail_info(s3_path)
    print(json.dumps(thumbnail_info, indent=2))


if __name__ == "__main__":
    main()
