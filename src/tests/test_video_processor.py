import pytest
import asyncio
from src.video_processor.video_processor import VideoProcessor
import logging

from dotenv import load_dotenv

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
                    "name": "video_test.mp4",
                    "bucket": "app.circleandclique.org",
                    "fileType": "Video",
                    "acl": "public-read",
                    "path": "original-files/videoc3fa0faa-7dd0-48f9-96f1-5f14528cd43a.mp4",
                    "lite": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/+v+i+d+e+o+c+3+f+a+0+f+a+a+-+7+d+d+0+-+4+8+f+9+-+9+6+f+1+-+5+f+1+4+5+2+8+c+d+4+3+a+-240p.mp4",
                    "small": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/+v+i+d+e+o+c+3+f+a+0+f+a+a+-+7+d+d+0+-+4+8+f+9+-+9+6+f+1+-+5+f+1+4+5+2+8+c+d+4+3+a+-360p.mp4",
                    "medium": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/+v+i+d+e+o+c+3+f+a+0+f+a+a+-+7+d+d+0+-+4+8+f+9+-+9+6+f+1+-+5+f+1+4+5+2+8+c+d+4+3+a+-480p.mp4",
                    "large": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/+v+i+d+e+o+c+3+f+a+0+f+a+a+-+7+d+d+0+-+4+8+f+9+-+9+6+f+1+-+5+f+1+4+5+2+8+c+d+4+3+a+-720p.mp4",
                    "original": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/original-files/videoc3fa0faa-7dd0-48f9-96f1-5f14528cd43a.mp4",
                    "version": 1,
                    "isDeleted": False,
                    "cachedLite": "",
                    "cachedOriginal": "https://dzv0fidwp2q1d.cloudfront.net/video/meicam_1723825301907.mp4",
                    "id": "67593ac9aced1565d6ea2bba",
                    "signed": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/+v+i+d+e+o+c+3+f+a+0+f+a+a+-+7+d+d+0+-+4+8+f+9+-+9+6+f+1+-+5+f+1+4+5+2+8+c+d+4+3+a+-signed.mp4",
                }
            ],
            "jobId": ":4838331B-5C8B-453C-938C-A45A2529AD2D",
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
