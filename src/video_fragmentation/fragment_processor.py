import logging
import asyncio
import os
import time
import ffmpeg
from typing import Dict, List, Any, Optional

from src.config.settings import settings
from src.video_processor.s3_video_analyzer import S3VideoAnalyzer
from src.video_fragmentation.video_segmenter import VideoSegmenter
from src.video_fragmentation.s3_fragment_uploader import S3FragmentUploader

logger = logging.getLogger(__name__)


class FragmentProcessor:
    """
    Main processor for video fragmentation workflow
    Stage 1: Basic fragmentation without AI titling
    """

    def __init__(self):
        # Video analyzer (for downloading from S3)
        self.video_analyzer = S3VideoAnalyzer(
            settings.AWS_ACCESS_KEY_ID,
            settings.AWS_SECRET_ACCESS_KEY,
            settings.AWS_REGION,
        )

        # Video segmenter (MoviePy)
        self.video_segmenter = VideoSegmenter(temp_dir=settings.FRAGMENTATION_TEMP_DIR)

        # S3 uploader
        self.s3_uploader = S3FragmentUploader(
            bucket_name=settings.FRAGMENTATION_OUTPUT_BUCKET,
            aws_access_key=settings.AWS_ACCESS_KEY_ID,
            aws_secret_key=settings.AWS_SECRET_ACCESS_KEY,
            region=settings.AWS_REGION,
        )

        logger.info("FragmentProcessor initialized")

    def should_fragment(
        self, message_data: Dict[str, Any], safety_score: int, content_flag: str
    ) -> bool:
        """
        Determine if video should be fragmented based on message flags and safety results

        Args:
            message_data: Kafka message data
            safety_score: Safety score from analysis (0-100)
            content_flag: Content flag from safety check

        Returns:
            True if fragmentation should proceed, False otherwise
        """
        # Check fragment flag
        if not message_data.get("fragment", False):
            logger.info("Fragment flag is false, skipping fragmentation")
            return False

        # Check safety score threshold
        if safety_score < settings.FRAGMENT_SAFETY_THRESHOLD:
            logger.warning(
                f"Safety score {safety_score} below threshold "
                f"{settings.FRAGMENT_SAFETY_THRESHOLD}, skipping fragmentation"
            )
            return False

        # Check content flag
        if content_flag not in ["SAFE", "RESTRICT_18+"]:
            logger.warning(
                f"Content flag '{content_flag}' not suitable for fragmentation"
            )
            return False

        logger.info(
            f"Fragmentation checks passed: safety_score={safety_score}, content_flag={content_flag}"
        )
        return True

    async def process_fragmentation(
        self, message_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Main fragmentation workflow

        Args:
            message_data: Kafka message data

        Returns:
            Fragmentation result or None if failed
        """
        start_time = time.time()
        job_id = message_data.get("jobId", "unknown")

        try:
            logger.info(f"Starting fragmentation for job {job_id}")

            # Extract configuration
            fragment_config = message_data.get("fragmentConfig", {})
            segment_duration = fragment_config.get(
                "requestedSegmentDuration", settings.FRAGMENT_DEFAULT_DURATION
            )

            # Validate segment duration
            if segment_duration not in settings.FRAGMENT_ALLOWED_DURATIONS:
                logger.error(
                    f"Invalid segment duration {segment_duration}. "
                    f"Allowed: {settings.FRAGMENT_ALLOWED_DURATIONS}"
                )
                return self._create_error_response(
                    job_id, f"Invalid segment duration: {segment_duration}"
                )

            # Get video URL
            video_url = self._extract_video_url(message_data)
            if not video_url:
                logger.error(f"No video URL found for job {job_id}")
                return self._create_error_response(job_id, "No video URL found")

            logger.info(f"Video URL: {video_url}")

            # Step 1: Download video from S3
            logger.info("Step 1: Downloading video from S3")
            video_path = await self._download_video(video_url, job_id)
            if not video_path:
                return self._create_error_response(job_id, "Video download failed")

            # Step 2: Segment video
            logger.info(f"Step 2: Segmenting video into {segment_duration}s chunks")
            segments = self.video_segmenter.segment_video(
                video_path=video_path, segment_duration=segment_duration, job_id=job_id
            )

            if not segments:
                return self._create_error_response(job_id, "Segmentation failed")

            logger.info(f"Created {len(segments)} fragments")

            # Step 3: Upload fragments to S3
            logger.info("Step 3: Uploading fragments to S3")
            upload_results = await self._upload_fragments(segments, job_id)

            # Step 4: Cleanup
            logger.info("Step 4: Cleaning up temp files")
            self._cleanup(video_path, job_id)

            # Calculate processing time
            processing_time = time.time() - start_time

            # Build response
            result = {
                "jobId": job_id,
                "status": "success",
                "fragmentationComplete": True,
                "totalEpisodes": len(upload_results),
                "segmentDuration": segment_duration,
                "episodes": upload_results,
                "processingTime": processing_time,
                "timestamp": int(time.time()),
            }

            logger.info(
                f"Fragmentation complete for job {job_id}: "
                f"{len(upload_results)} fragments in {processing_time:.2f}s"
            )

            return result

        except Exception as e:
            logger.error(f"Error in fragmentation workflow: {e}", exc_info=True)
            return self._create_error_response(job_id, str(e))

    def _extract_video_url(self, message_data: Dict[str, Any]) -> Optional[str]:
        """
        Extract video URL from message data

        Args:
            message_data: Kafka message data

        Returns:
            Video URL or None if not found
        """
        # Try videoDetails first
        video_details = message_data.get("videoDetails", {})
        video_url = video_details.get("originalVideoUrl")
        if video_url:
            return video_url

        # Fallback to files array
        files = message_data.get("files", [])
        if files:
            for file_item in files:
                if file_item.get("fileType") == "Video":
                    return file_item.get("original") or file_item.get("cachedOriginal")

        return None

    def _extract_description_text(self, message_data: Dict[str, Any]) -> str:
        """
        Extract description text from message data
        Combines title, primaryCaption, secondaryCaption, and description (all optional)

        Args:
            message_data: Kafka message data

        Returns:
            Combined description text (empty string if none exist)
        """
        description_parts = []

        # Get all optional fields
        title = message_data.get("title", "").strip()
        primary_caption = message_data.get("primaryCaption", "").strip()
        secondary_caption = message_data.get("secondaryCaption", "").strip()
        description = message_data.get("description", "").strip()

        # Add non-empty fields
        if title:
            description_parts.append(title)
        if secondary_caption:
            description_parts.append(secondary_caption)
        if primary_caption:
            description_parts.append(primary_caption)
        if description:
            description_parts.append(description)

        # Combine with newlines
        return "\n".join(description_parts)

    async def _download_video(self, video_url: str, job_id: str) -> Optional[str]:
        """
        Download video from S3

        Args:
            video_url: S3 URL of the video
            job_id: Job identifier

        Returns:
            Local path to downloaded video or None if failed
        """
        try:
            temp_dir = settings.FRAGMENTATION_TEMP_DIR
            os.makedirs(temp_dir, exist_ok=True)

            # Generate local path
            video_filename = f"{job_id}_source.mp4"
            local_path = os.path.join(temp_dir, video_filename)

            # Get presigned URL
            presigned_url = self.video_analyzer._get_presigned_url(video_url)

            logger.info(f"Downloading video to {local_path}")

            ffmpeg.input(presigned_url).output(
                local_path, codec="copy"
            ).overwrite_output().run(quiet=True)

            # Validate download
            if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
                logger.info(f"Video downloaded successfully: {local_path}")
                return local_path
            else:
                logger.error(f"Downloaded video is empty or missing: {local_path}")
                return None

        except Exception as e:
            logger.error(f"Error downloading video: {e}", exc_info=True)
            return None

    async def _upload_fragments(
        self, segments: List[Dict[str, Any]], job_id: str
    ) -> List[Dict[str, Any]]:
        """
        Upload all fragments to S3

        Args:
            segments: List of segment metadata with local paths
            job_id: Job identifier

        Returns:
            List of upload results
        """
        upload_results = []

        for segment in segments:
            fragment_number = segment["fragmentNumber"]
            local_path = segment["localPath"]

            upload_result = self.s3_uploader.upload_fragment(
                fragment_path=local_path,
                job_id=job_id,
                fragment_number=fragment_number,
                metadata=segment,
            )

            # Merge segment metadata with upload result
            episode_data = {**segment, **upload_result}

            # Remove local path from final result
            episode_data.pop("localPath", None)

            upload_results.append(episode_data)

        successful = sum(1 for r in upload_results if r.get("success", False))
        logger.info(f"Uploaded {successful}/{len(segments)} episodes successfully")

        return upload_results

    def _cleanup(self, video_path: str, job_id: str):
        """
        Clean up temporary files

        Args:
            video_path: Path to source video
            job_id: Job identifier
        """
        try:
            # Remove source video
            if os.path.exists(video_path):
                os.remove(video_path)
                logger.info(f"Removed source video: {video_path}")

            # Remove segment temp files
            self.video_segmenter.cleanup_temp_files(job_id)

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def _create_error_response(self, job_id: str, error_message: str) -> Dict[str, Any]:
        """
        Create error response

        Args:
            job_id: Job identifier
            error_message: Error description

        Returns:
            Error response dictionary
        """
        return {
            "jobId": job_id,
            "status": "failed",
            "fragmentationComplete": False,
            "error": error_message,
            "timestamp": int(time.time()),
        }
