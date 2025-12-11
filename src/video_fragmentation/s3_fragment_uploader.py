import logging
import boto3
import os
import json
import time
from typing import Dict, List, Any
from botocore.exceptions import ClientError

logger = logging.getLogger(__name__)


class S3FragmentUploader:
    """
    Handles uploading video fragments to S3
    """

    def __init__(
        self, bucket_name: str, aws_access_key: str, aws_secret_key: str, region: str
    ):
        self.bucket_name = bucket_name
        self.s3_client = boto3.client(
            "s3",
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=region,
        )
        logger.info(f"S3FragmentUploader initialized for bucket: {bucket_name}")

    def upload_fragment(
        self,
        fragment_path: str,
        job_id: str,
        fragment_number: int,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Upload a single fragment to S3 in job-specific folder

        Args:
            fragment_path: Local path to fragment file
            job_id: Job identifier (unique per upload)
            fragment_number: Fragment number
            metadata: Fragment metadata

        Returns:
            Upload result with S3 details
        """
        try:
            # S3 key structure: original-files/{jobId}/episode-{episodeNumber}.mp4
            # Easy to query: s3 ls s3://bucket/original-files/{jobId}/
            s3_key = f"original-files/{job_id}/episode-{fragment_number:04d}.mp4"

            logger.info(
                f"Uploading fragment {fragment_number} to s3://{self.bucket_name}/{s3_key}"
            )

            # Upload file with metadata as S3 object metadata
            self.s3_client.upload_file(
                fragment_path,
                self.bucket_name,
                s3_key,
                ExtraArgs={
                    "ContentType": "video/mp4",
                    "Metadata": {
                        "job-id": job_id,
                        "episode-number": str(fragment_number),
                        "start-time": str(metadata.get("startTime", 0)),
                        "end-time": str(metadata.get("endTime", 0)),
                        "duration": str(metadata.get("duration", 0)),
                    },
                },
            )

            # Generate S3 URL
            s3_url = f"s3://{self.bucket_name}/{s3_key}"

            # Generate presigned URL (valid for 7 days)
            presigned_url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=604800,  # 7 days
            )

            logger.info(f"Fragment {fragment_number} uploaded successfully")

            return {
                "success": True,
                "episodeNumber": fragment_number,
                "s3Key": s3_key,
                "s3Url": s3_url,
                "presignedUrl": presigned_url,
                "bucket": self.bucket_name,
                "fileSize": os.path.getsize(fragment_path),
            }

        except ClientError as e:
            logger.error(f"S3 upload failed for fragment {fragment_number}: {e}")
            return {
                "success": False,
                "episodeNumber": fragment_number,
                "error": str(e),
            }
        except Exception as e:
            logger.error(f"Unexpected error uploading fragment {fragment_number}: {e}")
            return {
                "success": False,
                "episodeNumber": fragment_number,
                "error": str(e),
            }
