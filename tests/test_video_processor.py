import pytest
import asyncio
from src.video_processor.video_processor import VideoProcessor
import logging
from src.config.settings import settings


from dotenv import load_dotenv


# Configure logging for the entire package
# Security: Force INFO level in production (never DEBUG)
environment = settings.ENVIRONMENT
log_level = logging.DEBUG if environment == "development" else logging.INFO

logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    # Add file output for production
    filename="/var/log/app.log" if environment == "production" else None,
)

# Reduce third-party noise
logging.getLogger("kafka").setLevel(logging.WARNING)


load_dotenv()


@pytest.mark.asyncio
async def test_process_videos_basic():
    """
    Basic test for VideoProcessor.process_video method

    Replace the example message_data with my actual JSON structure
    """

    message_data = {
        "data": {
            "files": [
                {
                    "name": "998fb13a-417e-4027-a751-a9c5ddf32c10.jpg",
                    "bucket": "app.circleandclique.org",
                    "fileType": "Image",
                    "acl": "public-read",
                    "path": "original-files/998fb13a-417e-4027-a751-a9c5ddf32c10.jpg",
                    "smallMpd": "",
                    "smallHsl": "",
                    "mediumMpd": "",
                    "mediumHsl": "",
                    "original": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/original-files/998fb13a-417e-4027-a751-a9c5ddf32c10.jpg",
                    "version": 1,
                    "isDeleted": False,
                    "id": "6810a82febe3d79ad2b053db",
                },
                {
                    "name": "a605cfcf-82dc-436f-939f-87d19ca4d100.mp4",
                    "bucket": "app.circleandclique.org",
                    "fileType": "Video",
                    "acl": "public-read",
                    "path": "original-files/a605cfcf-82dc-436f-939f-87d19ca4d100.mp4",
                    "smallMpd": "",
                    "smallHsl": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/a605cfcf-82dc-436f-939f-87d19ca4d100.m3u8",
                    "mediumMpd": "",
                    "mediumHsl": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/a605cfcf-82dc-436f-939f-87d19ca4d100.m3u8",
                    "original": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/original-files/a605cfcf-82dc-436f-939f-87d19ca4d100.mp4",
                    "version": 1,
                    "isDeleted": False,
                    "id": "6810a82febe3d79ad2b053dc",
                    "signed": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/a605cfcf-82dc-436f-939f-87d19ca4d100_signed.mp4",
                },
            ],
            "jobId": "091469EE-DEA8-4BAF-B1CF-A1C11EBB06B0",
        },
        "message": "transcode successful",
        "error": False,
        "statusCode": 200,
    }

    result = await VideoProcessor.process_videos(message_data)

    print(result)
    # Assertions based on the expected behavior of process_videos
    assert result is not None, "Processing should return a result"
    assert isinstance(result, dict), "Result should be a dictionary"

    @pytest.mark.asyncio
    async def test_process_videos_error_case():
        """
        Test VideoProcessor with an error scenario
        """
        error_message_data = {
            "data": {"files": [], "jobId": None},
            "message": "transcode failed",
            "error": True,
            "statusCode": 500,
        }

        result = await VideoProcessor.process_videos(error_message_data)

        # Assertions for error handling
        assert (
            result is None or result.get("error") is True
        ), "Should handle error cases"

    @pytest.mark.asyncio
    async def test_process_videos_invalid_input():
        """
        Test processing with completely invalid input
        """
        invalid_message_data = {"random": "data"}

        with pytest.raises(Exception) as excinfo:
            await VideoProcessor.process_videos(invalid_message_data)
