import time
import os
import google.generativeai as genai
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from src.config.settings import settings
import logging
from typing import Optional


# Configure logging
logging.basicConfig(
    level=getattr(logging, "INFO"),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


# Environment variable checks and initializations
gemini_key = settings.GEMINI_KEY
if not gemini_key:
    raise ValueError("GEMINI_KEY environment variable is not set")

# Initialize Google Generative AI
genai.configure(api_key=gemini_key)

# Ensure SLACK_BOT_TOKEN is set
SLACK_BOT_TOKEN = settings.SLACK_BOT_TOKEN
if not SLACK_BOT_TOKEN:
    raise ValueError("SLACK_BOT_TOKEN environment variable is not set")

# Initialize the Slack client
client = WebClient(token=SLACK_BOT_TOKEN)


def send_message_to_slack(channel: str, text: str):
    """Sends a message to the specified Slack channel."""
    try:
        response = client.chat_postMessage(channel=channel, text=text)
        print(f"Message sent to {channel}: {text}")
        return response
    except SlackApiError as e:
        print(f"Error sending message: {e.response['error']}")
        return None


def send_report_to_slack(
    video_file_name: str,
    video_file_link: str,
    success: bool,
    content: Optional[Exception] = None,
    error: Optional[Exception] = None,
    tags: Optional[Exception] = None,
):
    """Sends a well-formatted Slack message based on the success or failure of the tagging process."""
    if success:
        if content == "Good":
            message = (
                f":white_check_mark: *Video Tagging Successful* :white_check_mark:\n"
                f"*Video File:* {video_file_name}\n"
                f"*Video Link:* {video_file_link}\n"
                f"*Generated Tags:* {tags}"
            )
            send_message_to_slack(channel="testing_passed", text=message)
        else:
            message = (
                f":warning: *Video Tagging Harmful* :warning:\n"
                f"*Video File:* {video_file_name}\n"
                f"*Video Link:* {video_file_link}\n"
                f"*Generated Tags:* {tags}"
            )
            send_message_to_slack(channel="testing_review", text=message)

    else:
        message = (
            f":warning: *Video Tagging Failed* :warning:\n"
            f"*Video File:* {video_file_name}\n"
            f"*Video Link:* {video_file_link}\n"
            f"*Error Type:* {type(error).__name__}\n"
            f"*Error Message:* {str(error)}\n"
            f"*Suggested Action:* Review the file format or processing logs for more information.\n"
            f"*Timestamp:* {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}"
        )

        send_message_to_slack(channel="testing_review", text=message)

    return


def get_first_video_file_info(data):
    """Extract information about the first video file in the data."""
    video_files = []

    # Get all files from the data
    files = data.get("data", {}).get("files", [])

    # Filter only video files
    for file in files:
        if file.get("fileType") == "Video":
            video_files.append(file)

    if not video_files:
        # No video files found
        return "Unknown File", "Unknown Link"

    # Get the first video file
    first_video = video_files[0]

    # Get the name and link
    video_file_name = first_video.get("name", "Unknown File")

    # Use original URL as the primary source
    video_file_link = first_video.get("original", "Unknown Link")

    return video_file_name, video_file_link


def generate_video_tags(video_file_path, data):
    """Generates tags for a given video file using Google Generative AI."""
    video_file_name, video_file_link = get_first_video_file_info(data)

    try:
        video_file = genai.upload_file(video_file_path)

        while video_file.state.name == "PROCESSING":
            time.sleep(10)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError("Processing failed for the video file.")

        prompt = """
            Analyze the video content and select the most relevant tags from the list of categories provided below.
            Each video should be labeled with a minimum of 1 tag and a maximum of 5 tags. If the video belongs to
            multiple categories, choose the most appropriate and fitting tags. If the video cannot be processed due
            to restrictions or other issues, specify the reason for the block and suggest the most fitting category
            based on the available information.

            Categories:
            Harassment
            Hate-speech
            Dangerous
            Violence
            Gore
            Harmful-content
            Civic-integrity
            Comedy & Memes
            Entertainment & Afro-Centric
            Music & Dance
            Food & Recipes
            Sports & Fitness
            Beauty & Fashion
            Travel & Adventure
            Science & Education
            Gaming & Esports
            Daily Life & Vlogs
            DIY & Home Decor
            Family & Parenting
            Anime & Comics
            ASMR & Relaxation
            Pets & Animals
            Art & Design
            Tech & Gadgets
            Movies & TV Shows
            Trending & Viral
            Motivation & Self-Help
            Nature & Outdoors
            Relationship Tips
            Career & Entrepreneurship
            Personal Finance
            Language Learning
            Photography & Videography
            Books & Literature
            Meditation & Mindfulness
            Astrology & Spirituality
            True Crime & Mysteries
            History & Nostalgia
            Activism & Social Justice
            Cooking & Food Hacks
            Challenges & Pranks
            Supernatural & Paranormal
            Lifestyle & Influencer Content

            Instructions:
            Output the tags only, without adding any additional words.
            Ensure that no other text is included in the response apart from the specified tags or the block reason with category.
            Example Output:
            Comedy, Entertainment & Pop Culture, Trending & Viral
        """

        model = genai.GenerativeModel(model_name="gemini-2.0-flash")
        response = model.generate_content(
            [video_file, prompt], request_options={"timeout": 600}
        )

        tags = response.text if response else "blocked"
        harmful_tags = [
            "Harassment",
            "Hate-speech",
            "Dangerous",
            "Harmful-content",
            "Civic-integrity",
            "Gore",
            "Violence",
        ]

        if any(tag in tags for tag in harmful_tags):
            send_report_to_slack(
                video_file_name,
                video_file_link,
                content="harmful",
                success=True,
                tags=tags,
            )
        else:
            send_report_to_slack(
                video_file_name,
                video_file_link,
                content="Good",
                success=True,
                tags=tags,
            )

        return tags

    except Exception as e:
        logging.info(f"Error with tags: {str(e)}")
        send_report_to_slack(video_file_name, video_file_link, success=False, error=e)
        return f"Error generating tags: {str(e)}"
