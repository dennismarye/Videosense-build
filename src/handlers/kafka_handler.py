from confluent_kafka import Consumer, Producer, KafkaError
import json
import logging
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

class KafkaHandler:
    """
    Handles Kafka message consumption and production with robust error management.
    """
    
    def __init__(self, bootstrap_servers: str, consumer_group: str):
        """
        Initialize Kafka consumer and producer configurations.
        
        Args:
            bootstrap_servers (str): Kafka broker addresses
            consumer_group (str): Consumer group identifier
        """
        self.consumer_config = {
            'bootstrap.servers': bootstrap_servers,
            'group.id': consumer_group,
            'auto.offset.reset': 'earliest'
        }
        
        self.producer_config = {
            'bootstrap.servers': bootstrap_servers
        }
        
        self.consumer = Consumer(self.consumer_config)
        self.producer = Producer(self.producer_config)
    
    def consume(self, topics: List[str], timeout: float = 1.0) -> Optional[Dict]:
        """
        Consume messages from specified topics with advanced error handling.
        
        Args:
            topics (list): Kafka topics to consume from
            timeout (float): Consume timeout in seconds
        
        Returns:
            Optional message dictionary or None
        """
        try:
            self.consumer.subscribe(topics)
            msg = self.consumer.poll(timeout)
            
            if msg is None:
                return None
            
            if msg.error():
                if msg.error().code() == KafkaError._PARTITION_EOF:
                    logger.info('Reached end of partition')
                    return None
                else:
                    raise KafkaError(f"Consume error: {msg.error()}")
            
            return json.loads(msg.value().decode('utf-8'))
        
        except Exception as e:
            logger.error(f"Kafka consume error: {e}")
            return None
    
    def produce(self, topic: str, message: Dict) -> bool:
        """
        Produce messages to a Kafka topic with delivery confirmation.
        
        Args:
            topic (str): Target Kafka topic
            message (dict): Message to be produced
        
        Returns:
            bool: Indicating successful message production
        """
        try:
            serialized_msg = json.dumps(message).encode('utf-8')
            
            def delivery_report(err, msg):
                if err is not None:
                    logger.error(f'Message delivery failed: {err}')
                else:
                    logger.info(f'Message delivered to {msg.topic()}')
            
            self.producer.produce(
                topic, 
                value=serialized_msg, 
                callback=delivery_report
            )
            
            self.producer.flush()
            return True
        
        except Exception as e:
            logger.error(f"Kafka produce error: {e}")
            return False