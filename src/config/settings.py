import os
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv


load_dotenv()  # Explicitly load the .env file


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

    # Kafka Topic Configuration
    INPUT_TOPIC: str = "transcoding.transcode-result"
    OUTPUT_TOPIC: str = "classify.post_classify"

    # Directories
    OUTPUT_DIR: str = "compressed_videos"
    MERGED_OUTPUT_DIR: str = "merged_videos"

    # Server Configuration
    SERVER_HOST: str
    PORT: int
    SLACK_BOT_TOKEN: str
    GEMINI_KEY: str

    # Model configuration for environment variable loading
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )


@lru_cache()
def get_settings():
    """
    Cached settings retrieval to optimize performance
    """
    return Settings()


# Instantiate settings
settings = get_settings()
