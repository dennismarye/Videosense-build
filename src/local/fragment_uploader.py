"""
Local fragment uploader — saves fragments to the local filesystem
instead of uploading to S3.
"""

import logging
import os
import shutil
import time
from typing import Dict, Any

from src.config.settings import settings

logger = logging.getLogger(__name__)


class LocalFragmentUploader:
    """
    Drop-in replacement for S3FragmentUploader that saves to local disk.
    """

    def __init__(self, output_dir: str = None):
        self.output_dir = output_dir or settings.LOCAL_FRAGMENTS_DIR
        os.makedirs(self.output_dir, exist_ok=True)
        logger.info(f"LocalFragmentUploader initialized (output: {self.output_dir})")

    def upload_fragment(
        self,
        fragment_path: str,
        job_id: str,
        fragment_number: int,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Copy fragment to local output directory."""
        try:
            # Mirror the S3 key structure locally
            job_dir = os.path.join(self.output_dir, job_id)
            os.makedirs(job_dir, exist_ok=True)

            dest_filename = f"episode-{fragment_number:04d}.mp4"
            dest_path = os.path.join(job_dir, dest_filename)

            shutil.copy2(fragment_path, dest_path)

            file_size = os.path.getsize(dest_path)
            logger.info(
                f"[LOCAL] Fragment {fragment_number} saved: {dest_path} ({file_size} bytes)"
            )

            return {
                "success": True,
                "episodeNumber": fragment_number,
                "s3Key": f"local://{job_id}/{dest_filename}",
                "s3Url": f"file://{os.path.abspath(dest_path)}",
                "presignedUrl": f"file://{os.path.abspath(dest_path)}",
                "bucket": "local_storage",
                "fileSize": file_size,
            }

        except Exception as e:
            logger.error(f"Error saving fragment {fragment_number} locally: {e}")
            return {
                "success": False,
                "episodeNumber": fragment_number,
                "error": str(e),
            }
