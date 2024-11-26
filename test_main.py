import asyncio
import logging
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from src.config.settings import settings
from src.services.kafka_service import KafkaService
from src.video_processor.video_processor import VideoProcessor
from src.monitoring.health_check import KafkaMonitorService
from contextlib import asynccontextmanager

# Configure logging
logging.basicConfig(
    level=getattr(logging, "INFO"),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# Initialize services
kafka_service = KafkaService()
monitor = KafkaMonitorService()
video_processor = VideoProcessor()


# Background task to process Kafka messages
async def process_kafka_messages():
    """
    Continuously process Kafka messages in the background
    """
    def message_handler(message_data):
        # Asynchronous message processing
        asyncio.create_task(video_processor.process_videos(message_data))
    

    logging.info("Kafka message processor started.")
    try:
        async for message in kafka_service.consume(topics=[settings.INPUT_TOPIC,],message_handler=message_handler):
            # Process each message asynchronously
            asyncio.create_task(video_processor.process_videos(message))
    except asyncio.CancelledError:
        logging.info("Kafka message processor task cancelled.")
    except Exception as e:
        logging.error(f"Error in Kafka message processing: {e}")
        monitor.update_consumer_status("Failed")
    finally:
        logging.info("Kafka message processor stopped.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Lifespan handler for application startup and shutdown events
    """
    logging.info("Starting application...")
    app.state.kafka_task = asyncio.create_task(process_kafka_messages())
    yield
    logging.info("Shutting down application...")
    kafka_task = app.state.kafka_task
    if kafka_task:
        kafka_task.cancel()
        try:
            await kafka_task
        except asyncio.CancelledError:
            logging.info("Kafka task successfully cancelled.")
    await kafka_service.close_consumer()

# FastAPI Application
app = FastAPI(
    title="Video Processing Microservice",
    description="Kafka-based video processing microservice",
    version="1.0.0",
    lifespan=lifespan
)

@app.get("/health")
async def health_check():
    """Comprehensive health check endpoint"""
    status = monitor.get_health_status()
    return JSONResponse(
        status_code=200 if status['status'] == 'healthy' else 500,
        content=status
    )


def run():
    """
    Run the application
    """
    import uvicorn
    uvicorn.run(
        "test_main:app", 
        host=settings.SERVER_HOST, 
        port=settings.SERVER_PORT,
        reload=True
    )

if __name__ == "__main__":
    run()
