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



# Configure logging
logging.basicConfig(
    level=getattr(logging, "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Initialize services
kafka_service = KafkaService()
monitor = KafkaMonitorService()
video_processor = VideoProcessor()


# Run Kafka consumer in a thread
def run_kafka_consumer():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(kafka_service.consume(
            topics=[settings.INPUT_TOPIC],
            message_handler=process_kafka_message
        ))
    finally:
        loop.close()

# Background task to process Kafka messages
async def process_kafka_message(message_data):
    try:
        logging.info(f"Received message: {message_data}")
        processed_result = await video_processor.process_videos(message_data)
        if processed_result:
            await kafka_service.produce(
                topic=settings.OUTPUT_TOPIC,
                message=processed_result
            )
            logging.info(f"Produced result to {settings.OUTPUT_TOPIC}: {processed_result}")
        else:
            logging.warning("Processed result is empty or None.")
    except Exception as e:
        logging.error(f"Error in message processing: {e}")


import threading

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
    await kafka_service.close_consumer()
    logging.info("Kafka consumer stopped.")

# FastAPI Application
app = FastAPI(
    title="Video Processing Microservice",
    description="Kafka-based video processing microservice",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/")
async def health_check():
    """Comprehensive health check endpoint"""
    try:
        status = monitor.get_health_status()
        logging.info(f"Health Check Status: {status}")  # Add detailed logging
        return JSONResponse(
            status_code=200 if status['status'] == 'healthy' else 500,
            content=status
        )
    except Exception as e:
        logging.error(f"Health Check Failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


if __name__ == "__main__":

    try:
        # Explicit binding with multiple options
        uvicorn.run(
            "test_main:app",  # Confirm this matches your module name exactly
            host="0.0.0.0",  # Listen on all interfaces
            port=8000,
            reload=True,
            workers=1,
            log_level="debug"
        )
    except Exception as e:
        print(f"Server startup failed: {e}")
        import traceback
        traceback.print_exc()
