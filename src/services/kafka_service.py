import json
import logging
from typing import Dict, Any

from confluent_kafka import Consumer, Producer, KafkaError, KafkaException
from confluent_kafka.admin import AdminClient, NewTopic

from src.config.settings import settings
from src.monitoring.health_check import KafkaMonitorService

from aws_msk_iam_sasl_signer import MSKAuthTokenProvider


class KafkaService:
    """
    Comprehensive Kafka Service with robust error handling and monitoring
    """

    def __init__(self):
        # Initialize monitoring service
        self.monitor = KafkaMonitorService()

        # OAuth callback for AWS MSK authentication
        def oauth_cb(oauth_config):
            auth_token, expiry_ms = MSKAuthTokenProvider.generate_auth_token(
                settings.AWS_REGION
            )
            return auth_token, expiry_ms / 1000

        # Producer Configuration
        self.producer_conf = {
            "bootstrap.servers": settings.KAFKA_BROKER,
            "client.id": settings.MICROSERVICE_CLIENTID,
            "log_level": settings.LOG_LEVEL,
        }

        # SSL Configuration
        if settings.KAFKA_SSL:
            self.producer_conf.update(
                {
                    "security.protocol": "SASL_SSL",
                    "sasl.mechanisms": "OAUTHBEARER",
                    "oauth_cb": oauth_cb,
                }
            )
        else:
            self.producer_conf["security.protocol"] = "PLAINTEXT"

        # Consumer Configuration
        self.consumer_conf = {
            "bootstrap.servers": settings.KAFKA_BROKER,
            "client.id": settings.MICROSERVICE_CLIENTID,
            "group.id": settings.MICROSERVICE_GROUPID,
            "auto.offset.reset": "earliest",
            "enable.auto.commit": True,
        }

        # SSL Configuration for Consumer
        if settings.KAFKA_SSL:
            self.consumer_conf.update(
                {
                    "security.protocol": "SASL_SSL",
                    "sasl.mechanisms": "OAUTHBEARER",
                    "oauth_cb": oauth_cb,
                }
            )
        else:
            self.consumer_conf["security.protocol"] = "PLAINTEXT"

        # Initialize Producers and Consumers
        self.producer = None
        self.consumer = None
        self.admin_client = None

        self._initialize_clients()

    def _initialize_clients(self):
        """Initialize Kafka clients with error handling"""
        try:
            self.producer = Producer(self.producer_conf)
            self.consumer = Consumer(self.consumer_conf)

            # Create admin client for topic management
            self.admin_client = AdminClient({**self.producer_conf})

            try:
                cluster_metadata = self.admin_client.list_topics(timeout=10)
                print(f"Broker version likely supports Kafka {cluster_metadata}")
            except Exception as e:
                print(f"Failed to fetch metadata: {e}")

            # Update monitoring status
            self.monitor.update_kafka_connection(True)
            logging.info("Kafka clients initialized successfully")
        except Exception as e:
            self.monitor.update_kafka_connection(False)
            logging.error(f"Failed to initialize Kafka clients: {e}")
            raise

    async def create_topic(
        self, topic_name: str, num_partitions: int = 1, replication_factor: int = 1
    ):
        """
        Create a Kafka topic with error handling and idempotency
        """
        try:
            new_topic = NewTopic(topic_name, num_partitions, replication_factor)
            fs = self.admin_client.create_topics([new_topic])

            for topic, f in fs.items():
                try:
                    f.result()
                    logging.info(f"Topic '{topic}' created successfully")
                except KafkaException as e:
                    if e.args[0].code() == KafkaError.TOPIC_ALREADY_EXISTS:
                        logging.info(f"Topic '{topic}' already exists")
                    else:
                        logging.error(f"Failed to create topic '{topic}': {e}")
        except Exception as e:
            logging.error(f"Error in topic creation: {e}")

    async def produce(self, topic: str, data: Dict[str, Any]):
        """
        Produce message to Kafka topic with error handling
        """
        try:
            # Ensure topic exists
            await self.create_topic(topic)

            # Convert data to JSON
            data_json = json.dumps(data).encode("utf-8")

            # Produce message
            self.producer.produce(topic, value=data_json)
            self.producer.flush()

            logging.info(f"Produced message to topic {topic}")
            return {"status": "success", "message": "Message produced"}
        except Exception as e:
            logging.error(f"Error producing message: {e}")
            return {"status": "error", "message": str(e)}

    async def consume(self, topics: list, message_handler):
        """
        Consume messages from specified topics with advanced error handling
        """
        try:
            # Subscribe to topics
            self.consumer.subscribe(topics)
            logging.info(f"Subscribed to topics: {topics}")

            while True:
                msg = self.consumer.poll(1.0)
                # logging.info("Polling for messages...")

                if msg is None:
                    # logging.info("No message received.")
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logging.info(
                            f"Reached end of partition: {msg.topic()}[{msg.partition()}]"
                        )
                    else:
                        logging.error(f"Error while consuming messages: {msg.error()}")
                    continue

                # Process message
                try:
                    message_data = json.loads(msg.value().decode("utf-8"))
                    await message_handler(message_data)
                except json.JSONDecodeError:
                    logging.error("Failed to decode message")
                except Exception as e:
                    logging.error(f"Error processing message: {e}")

        except Exception as e:
            logging.error(f"Fatal error in consume method: {e}")
            self.monitor.update_consumer_status("Failed")
        finally:
            self.consumer.close()

    async def close_consumer(self):
        try:
            self.consumer.close()
            logging.info("Consumer is closed")
        except:
            logging.error("Issues closing the consumer")
