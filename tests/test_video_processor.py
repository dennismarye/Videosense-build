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
                    "name": "375e08f9-57de-48c8-96cd-3707eefb3159.mp4",
                    "bucket": "app.circleandclique.org",
                    "fileType": "Video",
                    "acl": "public-read",
                    "path": "original-files/375e08f9-57de-48c8-96cd-3707eefb3159.mp4",
                    "smallMpd": "",
                    "smallHsl": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/375e08f9-57de-48c8-96cd-3707eefb3159.m3u8",
                    "mediumMpd": "",
                    "mediumHsl": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/375e08f9-57de-48c8-96cd-3707eefb3159.m3u8",
                    "original": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/original-files/375e08f9-57de-48c8-96cd-3707eefb3159.mp4",
                    "version": 1,
                    "isDeleted": False,
                    "id": "680cc758ebe3d79ad2b053c0",
                    "signed": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/transcoded-videos/375e08f9-57de-48c8-96cd-3707eefb3159_signed.mp4",
                },
                {
                    "name": "de632aae-4ccc-4afa-a55b-3d94ad5d5607.png",
                    "bucket": "app.circleandclique.org",
                    "fileType": "Image",
                    "acl": "public-read",
                    "path": "original-files/de632aae-4ccc-4afa-a55b-3d94ad5d5607.png",
                    "smallMpd": "",
                    "smallHsl": "",
                    "mediumMpd": "",
                    "mediumHsl": "",
                    "original": "https://s3.eu-west-2.amazonaws.com/app.circleandclique.org/original-files/de632aae-4ccc-4afa-a55b-3d94ad5d5607.png",
                    "version": 1,
                    "isDeleted": False,
                    "id": "680cc758ebe3d79ad2b053c1",
                },
            ],
            "jobId": "60cbdb8e-26df-4dc3-abb3-28cb27482862",
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
