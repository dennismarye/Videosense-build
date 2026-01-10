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
from src.video_processor.video_processor import EnhancedVideoProcessor
from src.monitoring.health_check import KafkaMonitorService
from src.video_fragmentation.fragment_processor import FragmentProcessor

# Configure logging with New Relic integration
environment = settings.NODE_ENV
LOG_LEVEL = logging.DEBUG if environment == "development" else logging.INFO


def initialize_new_relic(env: str) -> None:
    """Initialize New Relic with configuration from settings"""
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

        logger = logging.getLogger(__name__)
        try:
            newrelic.agent.initialize()
            logger.info("New Relic monitoring initialized successfully")
        except Exception as e:
            logger.warning(
                f"Failed to initialize New Relic: {e}. Application will continue without monitoring.",
            )


initialize_new_relic(environment)

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(LOG_LEVEL)

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

# Enhanced Video Processor
enhanced_processor = EnhancedVideoProcessor()

# Fragment Processor (for video segmentation)
fragment_processor = FragmentProcessor()


@newrelic.agent.function_trace()
def run_kafka_consumer():
    """Run Kafka consumer in a thread with New Relic tracing"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        with newrelic.agent.BackgroundTask(
            application=newrelic.agent.application(), name="kafka_consumer_task"
        ):
            loop.run_until_complete(
                kafka_service.consume(
                    topics=[settings.INPUT_TOPIC],  # file-service topic
                    message_handler=process_kafka_message,
                    stop_event=stop_event,
                )
            )
    except Exception as e:
        newrelic.agent.record_exception()
        logging.error(f"Kafka consumer error: {e}")
    finally:
        loop.close()


@newrelic.agent.background_task()
async def process_kafka_message(message_data):
    """Process Kafka messages with enhanced two-stage video classification and fragmentation"""
    try:
        newrelic.agent.add_custom_attribute("kafka.topic", settings.INPUT_TOPIC)
        newrelic.agent.add_custom_attribute("message.size", len(str(message_data)))

        logging.info(f"Received CircoPost message: {message_data}")

        # Stage 1: Safety Check + Video Tagging
        with newrelic.agent.FunctionTrace(name="safety_check_and_tagging"):
            safety_result = await enhanced_processor.process_safety_and_tagging(
                message_data
            )

        if safety_result:
            # Produce to safety check topic
            with newrelic.agent.FunctionTrace(name="kafka_produce_safety"):
                await kafka_service.produce(
                    topic="classification.safety_check_passed", data=safety_result
                )
            logging.info(f"Produced safety check result: {safety_result}")

            # Check if fragmentation is requested AND safety passed
            safety_check = safety_result.get("safety_check", {})
            content_flag = safety_check.get("contentFlag", "")
            safety_score = safety_result.get("tags", [])
            # Calculate safety score (0-100) based on content flag
            calculated_safety_score = (
                100
                if content_flag == "SAFE"
                else (85 if content_flag == "RESTRICT_18+" else 0)
            )

            # CHECK: Should we fragment this video?
            if (
                settings.ENABLE_VIDEO_FRAGMENTATION
                and message_data.get("fragment", False)
                and fragment_processor.should_fragment(
                    message_data, calculated_safety_score, content_flag
                )
            ):
                # Fragmentation workflow
                logging.info(
                    f"Starting fragmentation workflow for job {message_data.get('jobId')}"
                )
                with newrelic.agent.FunctionTrace(name="video_fragmentation"):
                    fragment_result = await fragment_processor.process_fragmentation(
                        message_data
                    )

                if fragment_result:
                    # Produce to fragmentation output topic
                    with newrelic.agent.FunctionTrace(
                        name="kafka_produce_fragmentation"
                    ):
                        await kafka_service.produce(
                            topic=settings.FRAGMENT_OUTPUT_TOPIC, data=fragment_result
                        )
                    logging.info(f"Produced fragmentation result: {fragment_result}")
                    newrelic.agent.add_custom_attribute("fragmentation.success", True)
                    newrelic.agent.add_custom_attribute(
                        "fragmentation.total_fragments",
                        fragment_result.get("totalFragments", 0),
                    )

            # Stage 2: Quality Analysis + Description Analysis (only if safety check passed)
            if content_flag in ["SAFE", "RESTRICT_18+"]:
                with newrelic.agent.FunctionTrace(
                    name="quality_and_description_analysis"
                ):
                    # Extract AI context from Stage 1 results
                    ai_context = safety_result.get("aiContext", "")
                    quality_result = (
                        await enhanced_processor.process_quality_and_description(
                            message_data, ai_context=ai_context
                        )
                    )

                if quality_result:
                    # Produce to quality analysis topic
                    with newrelic.agent.FunctionTrace(name="kafka_produce_quality"):
                        await kafka_service.produce(
                            topic="classification.quality_analysis", data=quality_result
                        )
                    logging.info(f"Produced quality analysis result: {quality_result}")
            else:
                logging.warning(
                    f"Video failed safety check, skipping quality analysis and fragmentation. Job ID: {safety_result.get('jobId')}"
                )

        newrelic.agent.add_custom_attribute("processing.success", True)

    except Exception as e:
        newrelic.agent.record_exception()
        newrelic.agent.add_custom_attribute("processing.error", str(e))
        logging.error(f"Error in enhanced message processing: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan with New Relic monitoring"""
    logging.info("Starting Enhanced Video Classification Service...")

    newrelic.agent.record_custom_event(
        "ApplicationLifecycle", {"event": "startup", "environment": environment}
    )

    kafka_thread = threading.Thread(target=run_kafka_consumer, daemon=True)
    try:
        kafka_thread.start()
        initial_status = monitor.get_health_status()

        newrelic.agent.add_custom_attribute(
            "initial_health_status", initial_status["status"]
        )
        logging.info(f"Initial System Status: {initial_status}")

    except Exception as e:
        newrelic.agent.record_exception()
        logging.error(f"Application Startup Failed: {e}")
        monitor.update_kafka_connection(False)

    yield

    logging.info("Shutting down Enhanced Video Classification Service...")

    newrelic.agent.record_custom_event(
        "ApplicationLifecycle", {"event": "shutdown", "environment": environment}
    )

    stop_event.set()
    kafka_thread.join(timeout=5)
    await kafka_service.close_consumer()
    logging.info("Kafka consumer stopped.")


# FastAPI Application with New Relic
app = FastAPI(
    title="Enhanced Video Classification Service",
    description="Advanced Kafka-based video classification with safety, quality, and description analysis",
    version="2.0.0",
    lifespan=lifespan,
)


@app.get("/")
@newrelic.agent.web_transaction()
async def health_check():
    """Comprehensive health check endpoint with New Relic monitoring"""
    try:
        newrelic.agent.add_custom_attribute("endpoint", "health_check")

        status = monitor.get_health_status()

        # Add enhanced processor health check
        processor_status = enhanced_processor.get_health_status()
        status["enhanced_processor"] = processor_status

        newrelic.agent.add_custom_attribute("health_status", status["status"])
        if "kafka_connection" in status:
            newrelic.agent.add_custom_attribute(
                "kafka_connection", status["kafka_connection"]
            )

        newrelic.agent.record_custom_metric(
            "Custom/HealthCheck/Success", 1 if status["status"] == "healthy" else 0
        )

        logging.info(f"Health Check Status: {status}")

        return JSONResponse(
            status_code=200 if status["status"] == "healthy" else 500, content=status
        )

    except Exception as e:
        newrelic.agent.record_exception()
        newrelic.agent.record_custom_metric("Custom/HealthCheck/Error", 1)

        logging.error(f"Health Check Failed: {e}")
        return JSONResponse(
            status_code=500, content={"status": "error", "message": str(e)}
        )


@app.get("/metrics")
@newrelic.agent.web_transaction()
async def get_metrics():
    """Enhanced metrics endpoint for video classification monitoring"""
    try:
        metrics = {
            "service": "enhanced-video-classification",
            "version": "2.0.0",
            "environment": environment,
            "kafka_topics": {
                "input": settings.INPUT_TOPIC,
                "safety_output": "classification.safety_check_passed",
                "quality_output": "classification.quality_analysis",
            },
            "features": {
                "safety_check": True,
                "video_tagging": True,
                "quality_analysis": True,
                "description_analysis": True,
                "gemini_integration": True,
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
    print("Received shutdown signal, stopping Enhanced Video Classification Service...")

    newrelic.agent.record_custom_event(
        "ApplicationSignal", {"signal": sig, "action": "shutdown"}
    )

    stop_event.set()
    sys.exit(0)


if __name__ == "__main__":
    try:
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)

        newrelic.agent.record_custom_event(
            "ApplicationStart",
            {
                "method": "gunicorn",
                "environment": environment,
                "workers": os.getenv("WORKERS", "1"),
                "service": "enhanced-video-classification",
            },
        )

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
