import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import newrelic.agent
from pathlib import Path
from typing import Optional


# load_dotenv()  # Explicitly load the .env file
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")


class Settings(BaseSettings):
    """
    Centralized configuration management using Pydantic
    """

    # Kafka Configuration
    KAFKA_BROKER: str
    MICROSERVICE_CLIENTID: str
    MICROSERVICE_GROUPID: str
    KAFKA_ADMIN_CLIENT: str

    AWS_REGION: str
    WORKERS: int
    KAFKA_USERNAME: str
    KAFKA_PASSWORD: str
    KAFKA_AUTH_TYPE: str = "SCRAM"

    # SSL and Security
    KAFKA_SSL: bool = False

    # Logging
    LOG_LEVEL: str = "INFO"
    NODE_ENV: str

    # Kafka Topic Configuration
    INPUT_TOPIC: str = "classification.moderate_post"
    # OUTPUT_TOPIC: str = "classify.post_classify"

    # Enhanced Video Classification Topics
    SAFETY_OUTPUT_TOPIC: str = "classification.safety_check_passed"
    QUALITY_OUTPUT_TOPIC: str = "classification.quality_analysis"

    # Video Fragmentation Topics
    FRAGMENT_OUTPUT_TOPIC: str = "fragmentation.fragments_ready"

    # Directories
    OUTPUT_DIR: str = "compressed_videos"
    MERGED_OUTPUT_DIR: str = "merged_videos"
    TEMP_DIR: str = "/tmp/video_processing"
    FRAGMENTATION_TEMP_DIR: str = "/tmp/video_fragmentation"

    # Server Configuration
    SERVER_HOST: str
    KAFKA_CA_CERT_PATH: str = "./kafka.pem"
    PORT: int

    # AI/ML Service Configuration
    SLACK_BOT_TOKEN: str
    GEMINI_KEY: str
    GEMINI_MODEL: str = "gemini-2.5-flash"
    GEMINI_TIMEOUT: int = 600

    # Slack Configuration
    SLACK_CHANNEL_PASSED: str = "testing_passed"
    SLACK_CHANNEL_REVIEW: str = "testing_review"

    # Video Processing Configuration
    MAX_VIDEO_SIZE_MB: int = 500
    MAX_VIDEO_DURATION_SECONDS: int = 600
    SUPPORTED_VIDEO_FORMATS: str = "mp4,mov,avi,mkv,webm"

    # Quality Assessment Thresholds
    MIN_QUALITY_SCORE: int = 0
    MIN_RESOLUTION_WIDTH: int = 360
    MIN_RESOLUTION_HEIGHT: int = 240
    MIN_FPS: float = 15.0

    # Description Alignment Thresholds
    MIN_ALIGNMENT_SCORE: int = 0
    EXCELLENT_ALIGNMENT_SCORE: int = 90

    # FFmpeg Configuration
    FFMPEG_TIMEOUT: int = 300
    VIDEO_COMPRESSION_QUALITY: str = "medium"  # low, medium, high

    # Processing Configuration
    CLEANUP_TEMP_FILES: bool = True
    MAX_CONCURRENT_PROCESSING: int = 5

    # Feature Flags
    ENABLE_QUALITY_ANALYSIS: bool = True
    ENABLE_DESCRIPTION_ANALYSIS: bool = True
    ENABLE_SLACK_NOTIFICATIONS: bool = True
    ENABLE_CONTENT_MODERATION: bool = True
    ENABLE_VIDEO_FRAGMENTATION: bool = True

    # Video Fragmentation Configuration
    FRAGMENT_SAFETY_THRESHOLD: int = 30
    FRAGMENT_ALLOWED_DURATIONS: list = [90, 120, 180, 360]
    FRAGMENT_DEFAULT_DURATION: int = 180

    @property
    def FRAGMENTATION_OUTPUT_BUCKET(self) -> str:
        """
        Get S3 bucket based on environment
        - development, qa, staging → app.circleandclique.org
        - production → prod.circleandclique.org
        """
        if self.NODE_ENV.lower() == "production":
            return "prod.circleandclique.org"
        else:
            # dev, qa, staging all use the same bucket
            return "app.circleandclique.org"

    # Performance Configuration
    KAFKA_CONSUMER_TIMEOUT: float = 1.0
    KAFKA_PRODUCER_TIMEOUT: int = 10
    GEMINI_REQUEST_TIMEOUT: int = 600
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str

    def get_supported_video_formats(self) -> list:
        """Get list of supported video formats"""
        return [fmt.strip().lower() for fmt in self.SUPPORTED_VIDEO_FORMATS.split(",")]

    def get_ffmpeg_quality_settings(self) -> dict:
        """Get FFmpeg quality settings based on configuration"""
        quality_presets = {
            "low": {
                "video_bitrate": "300k",
                "audio_bitrate": "64k",
                "scale": "640:480",
                "fps": 15,
            },
            "medium": {
                "video_bitrate": "800k",
                "audio_bitrate": "128k",
                "scale": "1280:720",
                "fps": 24,
            },
            "high": {
                "video_bitrate": "2000k",
                "audio_bitrate": "192k",
                "scale": "1920:1080",
                "fps": 30,
            },
        }
        return quality_presets.get(
            self.VIDEO_COMPRESSION_QUALITY.lower(), quality_presets["medium"]
        )

    def get_slack_channels(self) -> dict:
        """Get Slack channels configuration"""
        return {
            "passed": self.SLACK_CHANNEL_PASSED,
            "review": self.SLACK_CHANNEL_REVIEW,
        }

    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.NODE_ENV.lower() == "development"

    def is_production(self) -> bool:
        """Check if running in production mode"""
        return self.NODE_ENV.lower() == "production"

    def get_kafka_topics(self) -> dict:
        """Get all Kafka topics configuration"""
        return {
            "input": self.INPUT_TOPIC,
            "output": self.OUTPUT_TOPIC,
            "safety_output": self.SAFETY_OUTPUT_TOPIC,
            "quality_output": self.QUALITY_OUTPUT_TOPIC,
        }


class ProductionSettings(Settings):
    # Production-only fields
    NEW_RELIC_LICENSE_KEY: str
    NEW_RELIC_APP_NAME: str

    # Model configuration for environment variable loading
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


def get_settings():
    """Factory function to return appropriate settings class"""
    environment = os.getenv("NODE_ENV", "development").lower()

    if environment == "production":
        return ProductionSettings()
    else:
        return Settings()


# Instantiate settings
settings = get_settings()
