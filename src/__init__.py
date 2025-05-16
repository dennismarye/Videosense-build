"""
Kafka Consumer Producer Service
Main package initialization.
"""

import logging
from src.config.settings import settings

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
