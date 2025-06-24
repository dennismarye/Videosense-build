import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

# New Relic imports - must be imported before other application modules
import newrelic.agent
from newrelic.agent import NewRelicContextFormatter

from src.config.settings import settings
from src.services.kafka_service import KafkaService
from src.video_processor.video_processor import VideoProcessor
from src.monitoring.health_check import KafkaMonitorService


# Configure logging with New Relic integration
environment = settings.NODE_ENV

log_level = logging.DEBUG if environment == "development" else logging.INFO


def initialize_new_relic(env: str) -> None:
    """
    Initialize New Relic with configuration from settings
    """

    if env == "production":

        # Set New Relic configuration as environment variables
        os.environ["NEW_RELIC_LICENSE_KEY"] = settings.NEW_RELIC_LICENSE_KEY
        os.environ["NEW_RELIC_APP_NAME"] = settings.NEW_RELIC_APP_NAME
        os.environ["NEW_RELIC_LOG_FILE"] = "stdout"
        os.environ["NEW_RELIC_LOG_LEVEL"] = "info"
        os.environ["NEW_RELIC_MONITOR_MODE"] = "true"
        os.environ["NEW_RELIC_HIGH_SECURITY"] = "false"
        os.environ["NEW_RELIC_TRANSACTION_TRACER_ENABLED"] = "true"
        os.environ["NEW_RELIC_TRANSACTION_TRACER_TRANSACTION_THRESHOLD"] = "apdex_f"
        os.environ["NEW_RELIC_TRANSACTION_TRACER_RECORD_SQL"] = "obfuscated"
        os.environ["NEW_RELIC_TRANSACTION_TRACER_STACK_TRACE_THRESHOLD"] = "0.5"
        os.environ["NEW_RELIC_TRANSACTION_TRACER_EXPLAIN_ENABLED"] = "true"
        os.environ["NEW_RELIC_TRANSACTION_TRACER_EXPLAIN_THRESHOLD"] = "0.5"
        os.environ["NEW_RELIC_ERROR_COLLECTOR_ENABLED"] = "true"
        os.environ["NEW_RELIC_BROWSER_MONITORING_AUTO_INSTRUMENT"] = "true"
        os.environ["NEW_RELIC_THREAD_PROFILER_ENABLED"] = "true"
        os.environ["NEW_RELIC_DISTRIBUTED_TRACING_ENABLED"] = "true"

        # Initialize New Relic agent
        try:
            newrelic.agent.initialize()
            logging.info("New Relic monitoring initialized successfully")
        except Exception as e:
            logging.warning(
                f"Failed to initialize New Relic: {e}. Application will continue without monitoring."
            )


initialize_new_relic(environment)


# Create a custom formatter that includes New Relic context
class CustomNewRelicFormatter(NewRelicContextFormatter):
    def format(self, record):
        # Add custom formatting while preserving New Relic context
        formatted = super().format(record)
        return f"%(asctime)s - %(name)s - %(levelname)s - {formatted}"


# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(log_level)

# Create handler with New Relic formatter
handler = logging.StreamHandler()
formatter = NewRelicContextFormatter()
handler.setFormatter(formatter)
root_logger.addHandler(handler)

# Add file handler for production with New Relic context
if environment == "production":
    file_handler = logging.FileHandler("app.log")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

# Reduce third-party noise
logging.getLogger("kafka").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.INFO)
logging.getLogger("gunicorn").setLevel(logging.INFO)

# Initialize services
kafka_service = KafkaService()
monitor = KafkaMonitorService()
stop_event = threading.Event()


# Decorator for New Relic transaction tracking
@newrelic.agent.function_trace()
def run_kafka_consumer():
    """Run Kafka consumer in a thread with New Relic tracing"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        # Add New Relic background task context
        with newrelic.agent.BackgroundTask(
            application=newrelic.agent.application(), name="kafka_consumer_task"
        ):
            loop.run_until_complete(
                kafka_service.consume(
                    topics=[settings.INPUT_TOPIC],
                    message_handler=process_kafka_message,
                    stop_event=stop_event,
                )
            )
    except Exception as e:
        # Record exception with New Relic
        newrelic.agent.record_exception()
        logging.error(f"Kafka consumer error: {e}")
    finally:
        loop.close()


# Background task to process Kafka messages with New Relic tracing
@newrelic.agent.background_task()
async def process_kafka_message(message_data):
    """Process Kafka messages with New Relic monitoring"""
    try:
        # Add custom attributes for better monitoring
        newrelic.agent.add_custom_attribute("kafka.topic", settings.INPUT_TOPIC)
        newrelic.agent.add_custom_attribute("message.size", len(str(message_data)))

        logging.info(f"Received message: {message_data}")

        # Track video processing as a separate trace
        with newrelic.agent.FunctionTrace(name="video_processing"):
            processed_result = await VideoProcessor.process_videos(message_data)

        if processed_result:
            # Track Kafka production
            with newrelic.agent.FunctionTrace(name="kafka_produce"):
                await kafka_service.produce(
                    topic=settings.OUTPUT_TOPIC, data=processed_result
                )

            newrelic.agent.add_custom_attribute("processing.success", True)
            logging.info(
                f"Produced result to {settings.OUTPUT_TOPIC}: {processed_result}"
            )
        else:
            newrelic.agent.add_custom_attribute("processing.success", False)
            logging.warning("Processed result is empty or None.")

    except Exception as e:
        # Record exception with New Relic
        newrelic.agent.record_exception()
        newrelic.agent.add_custom_attribute("processing.error", str(e))
        logging.error(f"Error in message processing: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with New Relic monitoring"""
    logging.info("Starting application...")

    # Add New Relic custom event for application startup
    newrelic.agent.record_custom_event(
        "ApplicationLifecycle", {"event": "startup", "environment": environment}
    )

    kafka_thread = threading.Thread(target=run_kafka_consumer, daemon=True)
    try:
        kafka_thread.start()
        initial_status = monitor.get_health_status()

        # Record initial health status with New Relic
        newrelic.agent.add_custom_attribute(
            "initial_health_status", initial_status["status"]
        )
        logging.info(f"Initial System Status: {initial_status}")

    except Exception as e:
        newrelic.agent.record_exception()
        logging.error(f"Application Startup Failed: {e}")
        monitor.update_kafka_connection(False)

    yield

    logging.info("Shutting down application...")

    # Record shutdown event
    newrelic.agent.record_custom_event(
        "ApplicationLifecycle", {"event": "shutdown", "environment": environment}
    )

    # Signal the Kafka consumer thread to stop
    stop_event.set()
    # Wait for the thread to finish (with a timeout to prevent hanging)
    kafka_thread.join(timeout=5)
    # Additional cleanup
    await kafka_service.close_consumer()
    logging.info("Kafka consumer stopped.")


# FastAPI Application with New Relic
app = FastAPI(
    title="Video Processing Microservice",
    description="Kafka-based video processing microservice with New Relic monitoring",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
@newrelic.agent.web_transaction()
async def health_check():
    """Comprehensive health check endpoint with New Relic monitoring"""
    try:
        # Add custom attributes for monitoring
        newrelic.agent.add_custom_attribute("endpoint", "health_check")

        status = monitor.get_health_status()

        # Record health status metrics
        newrelic.agent.add_custom_attribute("health_status", status["status"])
        if "kafka_connection" in status:
            newrelic.agent.add_custom_attribute(
                "kafka_connection", status["kafka_connection"]
            )

        # Record custom metric for health checks
        newrelic.agent.record_custom_metric(
            "Custom/HealthCheck/Success", 1 if status["status"] == "healthy" else 0
        )

        logging.info(f"Health Check Status: {status}")

        return JSONResponse(
            status_code=200 if status["status"] == "healthy" else 500, content=status
        )

    except Exception as e:
        # Record exception and error metrics
        newrelic.agent.record_exception()
        newrelic.agent.record_custom_metric("Custom/HealthCheck/Error", 1)

        logging.error(f"Health Check Failed: {e}")
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@app.get("/metrics")
@newrelic.agent.web_transaction()
async def get_metrics():
    """Custom metrics endpoint for additional monitoring"""
    try:
        # You can add custom business metrics here
        metrics = {
            "service": "video-processing",
            "version": "1.0.0",
            "environment": environment,
            "kafka_topics": {
                "input": settings.INPUT_TOPIC,
                "output": settings.OUTPUT_TOPIC,
            },
        }

        newrelic.agent.add_custom_attribute("endpoint", "metrics")
        return JSONResponse(status_code=200, content=metrics)

    except Exception as e:
        newrelic.agent.record_exception()
        logging.error(f"Metrics endpoint error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


def signal_handler(sig, frame):
    """Signal handler with New Relic event recording"""
    print("Received shutdown signal, stopping application...")

    # Record shutdown signal event
    newrelic.agent.record_custom_event(
        "ApplicationSignal", {"signal": sig, "action": "shutdown"}
    )

    stop_event.set()
    sys.exit(0)


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        # Record application start event
        newrelic.agent.record_custom_event(
            "ApplicationStart",
            {
                "method": "gunicorn",
                "environment": environment,
                "workers": os.getenv("WORKERS", "1"),
            },
        )

        # Construct the gunicorn command
        cmd = [
            "gunicorn",
            "main:app",
            "--bind",
            f"{os.getenv('SERVER_HOST', '0.0.0.0')}:{os.getenv('PORT', '8000')}",
            "--workers",
            os.getenv("WORKERS", "1"),
            "--log-level",
            os.getenv("LOG_LEVEL", "info"),
            "-k",
            "uvicorn.workers.UvicornWorker",
        ]

        # Start the Gunicorn server
        subprocess.run(cmd, check=True)

    except subprocess.CalledProcessError as e:
        newrelic.agent.record_exception()
        print(f"Server startup failed with exit code {e.returncode}: {e}")
        import traceback

        traceback.print_exc()

    except Exception as ex:
        newrelic.agent.record_exception()
        print(f"Unexpected error: {ex}")
        import traceback

        traceback.print_exc()
