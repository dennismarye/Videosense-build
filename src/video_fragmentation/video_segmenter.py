import logging
import os
import math
from typing import List, Dict, Any, Optional
from moviepy.editor import VideoFileClip
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoSegmenter:
    """
    Handles video segmentation using MoviePy
    Cuts videos into precise time-based segments
    """

    def __init__(self, temp_dir: str = "/tmp/video_fragmentation"):
        self.temp_dir = temp_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        logger.info(f"VideoSegmenter initialized with temp_dir: {temp_dir}")

    def segment_video(
        self, video_path: str, segment_duration: int, job_id: str
    ) -> List[Dict[str, Any]]:
        """
        Segment video into chunks of specified duration

        Args:
            video_path: Path to the source video file
            segment_duration: Duration of each segment in seconds (180 or 360)
            job_id: Job identifier for organizing output

        Returns:
            List of segment metadata dictionaries
        """
        try:
            logger.info(
                f"Starting segmentation for {video_path} with duration {segment_duration}s"
            )

            # Create job-specific output directory
            output_dir = os.path.join(self.temp_dir, job_id)
            os.makedirs(output_dir, exist_ok=True)

            # Load video and get duration
            video = VideoFileClip(video_path)
            total_duration = video.duration
            total_segments = math.ceil(total_duration / segment_duration)

            logger.info(
                f"Video duration: {total_duration}s, "
                f"Segment duration: {segment_duration}s, "
                f"Total segments: {total_segments}"
            )

            segments = []

            for i in range(total_segments):
                start_time = i * segment_duration
                end_time = min((i + 1) * segment_duration, total_duration)
                fragment_number = i + 1

                logger.info(f"Processing fragment {fragment_number}/{total_segments}")

                # Cut segment
                segment_path = self._cut_segment(
                    video=video,
                    start_time=start_time,
                    end_time=end_time,
                    fragment_number=fragment_number,
                    output_dir=output_dir,
                )

                if segment_path:
                    segment_metadata = {
                        "fragmentNumber": fragment_number,
                        "startTime": start_time,
                        "endTime": end_time,
                        "duration": end_time - start_time,
                        "localPath": segment_path,
                        "filename": os.path.basename(segment_path),
                        "fileSize": os.path.getsize(segment_path),
                    }
                    segments.append(segment_metadata)
                    logger.info(f"Fragment {fragment_number} created: {segment_path}")
                else:
                    logger.error(f"Failed to create fragment {fragment_number}")

            # Close video file
            video.close()

            logger.info(
                f"Segmentation complete: {len(segments)}/{total_segments} fragments created"
            )
            return segments

        except Exception as e:
            logger.error(f"Error in video segmentation: {e}", exc_info=True)
            raise

    def _cut_segment(
        self,
        video: VideoFileClip,
        start_time: float,
        end_time: float,
        fragment_number: int,
        output_dir: str,
    ) -> Optional[str]:
        """
        Cut a specific segment from the video

        Args:
            video: VideoFileClip object
            start_time: Start time in seconds
            end_time: End time in seconds
            fragment_number: Fragment number (for naming)
            output_dir: Directory to save the segment

        Returns:
            Path to the created segment file or None if failed
        """
        try:
            # Extract subclip
            segment = video.subclip(start_time, end_time)

            # Generate filename
            segment_filename = f"fragment_{fragment_number:04d}.mp4"
            segment_path = os.path.join(output_dir, segment_filename)

            # Write segment with optimized settings
            segment.write_videofile(
                segment_path,
                codec="libx264",
                audio_codec="aac",
                temp_audiofile=f"{output_dir}/temp-audio-{fragment_number}.m4a",
                remove_temp=True,
                fps=video.fps,
                preset="medium",
                threads=4,
                logger=None,  # Suppress MoviePy verbose output
            )

            # Close segment
            segment.close()

            # Validate output
            if os.path.exists(segment_path) and os.path.getsize(segment_path) > 0:
                return segment_path
            else:
                logger.error(f"Segment file is empty or missing: {segment_path}")
                return None

        except Exception as e:
            logger.error(f"Error cutting segment {fragment_number}: {e}", exc_info=True)
            return None

    def cleanup_temp_files(self, job_id: str):
        """
        Clean up temporary files for a job

        Args:
            job_id: Job identifier
        """
        try:
            job_dir = os.path.join(self.temp_dir, job_id)
            if os.path.exists(job_dir):
                import shutil

                shutil.rmtree(job_dir)
                logger.info(f"Cleaned up temp files for job {job_id}")
        except Exception as e:
            logger.error(f"Error cleaning up temp files for job {job_id}: {e}")

    def get_video_metadata(self, video_path: str) -> Dict[str, Any]:
        """
        Extract basic metadata from video file

        Args:
            video_path: Path to video file

        Returns:
            Dictionary with video metadata
        """
        try:
            video = VideoFileClip(video_path)
            metadata = {
                "duration": video.duration,
                "fps": video.fps,
                "size": video.size,  # (width, height)
                "width": video.w,
                "height": video.h,
                "aspect_ratio": video.aspect_ratio,
                "rotation": getattr(video, "rotation", 0),
            }
            video.close()
            return metadata
        except Exception as e:
            logger.error(f"Error extracting video metadata: {e}")
            return {}
