import time
import os
import google.generativeai as genai
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError


gemini_key = os.getenv("GEMINI_KEY")

# Initialize Google Generative AI
genai.configure(api_key=gemini_key)


# Ensure your environment variables are set
# SLACK_BOT_TOKEN should be the "Bot User OAuth Token" (e.g., xoxb-xxx...)
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")


# Initialize the Slack client with your Bot Token
client = WebClient(token=SLACK_BOT_TOKEN)


def send_message_to_slack(channel: str, text: str):
    try:
        response = client.chat_postMessage(channel=channel, text=text)
        print(f"Message sent to {channel}: {text}")
        return response
    except SlackApiError as e:
        print(f"Error sending message: {e.response['error']}")
        return None


# Function to generate video tags
def generate_video_tags(video_file_path, data):
    try:
        video_file = genai.upload_file(video_file_path)

        while video_file.state.name == "PROCESSING":
            time.sleep(10)
            video_file = genai.get_file(video_file.name)

        if video_file.state.name == "FAILED":
            raise ValueError(video_file.state.name)

        prompt = """
                Analyze the video content and select the most relevant tags from the list of categories provided below. Each video should be labeled with a minimum of 1 tag and a maximum of 5 tags. If the video belongs to multiple categories, choose the most appropriate and fitting tags. If the video cannot be processed due to restrictions or other issues, specify the reason for the block and suggest the most fitting category based on the available information.
                Categories:
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

        model = genai.GenerativeModel(model_name="gemini-1.5-flash")
        response = model.generate_content(
            [video_file, prompt], request_options={"timeout": 600}
        )
        return response.text if response else "blocked"
    except Exception as e:
        send_message_to_slack(
            "testing", f"Error generating tags for this video {data}: Error is {str(e)}"
        )
        return f"Error generating tags: {str(e)}"
