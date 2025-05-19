import asyncio
import logging
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.config.settings import settings
from src.services.kafka_service import KafkaService
from src.video_processor.video_processor import VideoProcessor
from src.monitoring.health_check import KafkaMonitorService
from contextlib import asynccontextmanager
import asyncio
import uvicorn
import threading
import os
import signal
import sys
import subprocess


# Configure logging for the entire package
# Security: Force INFO level in production (never DEBUG)
environment = settings.NODE_ENV
log_level = logging.DEBUG if environment == "development" else logging.INFO

logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    # Add file output for production
    filename=None,
)

# Reduce third-party noise
logging.getLogger("kafka").setLevel(logging.WARNING)

# Initialize services
kafka_service = KafkaService()
monitor = KafkaMonitorService()
# Add this at the top of your file
stop_event = threading.Event()


# Run Kafka consumer in a thread
def run_kafka_consumer():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            kafka_service.consume(
                topics=[settings.INPUT_TOPIC],
                message_handler=process_kafka_message,
                stop_event=stop_event,  # Pass the stop event
            )
        )
    finally:
        loop.close()


# Background task to process Kafka messages
async def process_kafka_message(message_data):
    try:
        logging.info(f"Received message: {message_data}")
        processed_result = await VideoProcessor.process_videos(message_data)
        if processed_result:
            await kafka_service.produce(
                topic=settings.OUTPUT_TOPIC, data=processed_result
            )
            logging.info(
                f"Produced result to {settings.OUTPUT_TOPIC}: {processed_result}"
            )
        else:
            logging.warning("Processed result is empty or None.")
    except Exception as e:
        logging.error(f"Error in message processing: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.info("Starting application...")
    kafka_thread = threading.Thread(target=run_kafka_consumer, daemon=True)
    try:
        kafka_thread.start()
        initial_status = monitor.get_health_status()
        logging.info(f"Initial System Status: {initial_status}")
    except Exception as e:
        logging.error(f"Application Startup Failed: {e}")
        monitor.update_kafka_connection(False)

    yield

    logging.info("Shutting down application...")
    # Signal the Kafka consumer thread to stop
    stop_event.set()
    # Wait for the thread to finish (with a timeout to prevent hanging)
    kafka_thread.join(timeout=5)
    # Additional cleanup
    await kafka_service.close_consumer()
    logging.info("Kafka consumer stopped.")


# FastAPI Application
app = FastAPI(
    title="Video Processing Microservice",
    description="Kafka-based video processing microservice",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def health_check():
    """Comprehensive health check endpoint"""
    try:
        status = monitor.get_health_status()
        logging.info(f"Health Check Status: {status}")  # Add detailed logging
        return JSONResponse(
            status_code=200 if status["status"] == "healthy" else 500, content=status
        )
    except Exception as e:
        logging.error(f"Health Check Failed: {e}")
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


def signal_handler(sig, frame):
    print("Received shutdown signal, stopping application...")
    stop_event.set()
    sys.exit(0)


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        # Construct the gunicorn command
        cmd = [
            "gunicorn",
            "main:app",  # Confirm this matches your module and app name exactly
            "--bind",
            f"{os.getenv('SERVER_HOST')}:{os.getenv('PORT','8000')}",  # Host and port
            "--workers",
            os.getenv("WORKERS", "1"),  # Number of workers
            "--log-level",
            os.getenv("LOG_LEVEL", "info"),  # Logging level
            "-k",
            "uvicorn.workers.UvicornWorker",  # Specify the ASGI worker
        ]

        # Start the Gunicorn server
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Server startup failed with exit code {e.returncode}: {e}")
        import traceback

        traceback.print_exc()
    except Exception as ex:
        print(f"Unexpected error: {ex}")
        import traceback

        traceback.print_exc()
