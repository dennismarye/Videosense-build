# test_producer.py - End-to-end Kafka testing script
import json
import time
import logging
from typing import Dict, Any
from confluent_kafka import Producer
from datetime import datetime, timezone
import argparse
import sys

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class SparksTestProducer:
    """
    Test producer for Circo Sparks Kafka integration
    Tests all input topics that your consumer listens to
    """

    def __init__(self, kafka_broker: str = "localhost:9092"):
        self.kafka_broker = kafka_broker
        self.producer_conf = {
            "bootstrap.servers": kafka_broker,
            "client.id": "sparks-test-producer",
            "acks": "all",
            "retries": 3,
        }

        self.producer = Producer(self.producer_conf)

        # Topics your consumer listens to (INPUT topics)
        self.input_topics = {
            # Command topics
            "user_sparks_update": "sparks.commands.user_sparks_update",
            "notification_create": "sparks.commands.notification_create",
            "demographics_update": "sparks.commands.demographics_update",
            # Event topics
            "user_registered": "sparks.events.user_registered",
            "content_posted": "sparks.events.content_posted",
            "engagement_activity": "sparks.events.engagement_activity",
        }

        logger.info(f"Test producer initialized for broker: {kafka_broker}")

    def delivery_callback(self, err, msg):
        """Callback for message delivery confirmation"""
        if err:
            logger.error(f"❌ Message delivery failed: {err}")
        else:
            logger.info(
                f"✅ Message delivered to {msg.topic()} [partition: {msg.partition()}, offset: {msg.offset()}]"
            )

    def produce_message(self, topic_key: str, data: Dict[str, Any]) -> bool:
        """Produce a test message to specified topic"""
        try:
            topic = self.input_topics.get(topic_key)
            if not topic:
                logger.error(f"❌ Unknown topic key: {topic_key}")
                return False

            # Add test metadata
            test_data = {
                **data,
                "timestamp": int(time.time() * 1000),
                "test_run": True,
                "producer": "sparks-test-producer",
            }

            message_json = json.dumps(test_data, indent=2).encode("utf-8")
            message_key = data.get("user_id", data.get("creator_id", "test")).encode(
                "utf-8"
            )

            logger.info(f"🚀 Producing to topic: {topic}")
            logger.info(f"📝 Message: {json.dumps(test_data, indent=2)}")

            self.producer.produce(
                topic=topic,
                key=message_key,
                value=message_json,
                callback=self.delivery_callback,
            )

            self.producer.flush(timeout=10)
            return True

        except Exception as e:
            logger.error(f"❌ Error producing message: {e}")
            return False

    # ============================================================================
    # TEST SCENARIOS - Command Topics
    # ============================================================================

    def test_user_sparks_update(self, user_id: str = "testuser123", sparks: int = 500):
        """Test: sparks.commands.user_sparks_update"""
        logger.info("🔥 Testing User Sparks Update Command")

        test_data = {
            "user_id": user_id,
            "username": "testuser",
            "sparks_amount": sparks,
            "source": "test_producer",
            "reason": "Testing milestone detection and broadcasts",
        }

        return self.produce_message("user_sparks_update", test_data)

    def test_notification_create(self, user_id: str = "testuser123"):
        """Test: sparks.commands.notification_create"""
        logger.info("📢 Testing Notification Create Command")

        test_data = {
            "user_id": user_id,
            "type": "achievement",
            "message": "🎉 Test achievement unlocked!",
            "priority": "high",
            "achievement_type": "test_milestone",
        }

        return self.produce_message("notification_create", test_data)

    def test_demographics_update(self, creator_id: str = "creator123"):
        """Test: sparks.commands.demographics_update"""
        logger.info("📊 Testing Demographics Update Command")

        test_data = {
            "creator_id": creator_id,
            "demographic_type": "age_group",
            "data": {
                "18-24": {"fan_count": 1500, "total_sparks": 12000},
                "25-34": {"fan_count": 2000, "total_sparks": 18000},
                "35-44": {"fan_count": 800, "total_sparks": 9500},
            },
            "update_reason": "test_demographics_processing",
        }

        return self.produce_message("demographics_update", test_data)

    # ============================================================================
    # TEST SCENARIOS - Event Topics
    # ============================================================================

    def test_user_registered(self, user_id: str = "newuser456"):
        """Test: sparks.events.user_registered"""
        logger.info("👤 Testing User Registered Event")

        test_data = {
            "user_id": user_id,
            "username": "newuser_test",
            "email": "newuser@test.com",
            "display_name": "Test New User",
            "registration_source": "test_producer",
            "country": "Nigeria",
            "age_group": "25-34",
        }

        return self.produce_message("user_registered", test_data)

    def test_content_posted(self, creator_id: str = "creator123"):
        """Test: sparks.events.content_posted"""
        logger.info("🎬 Testing Content Posted Event")

        test_data = {
            "creator_id": creator_id,
            "username": "test_creator",
            "content_type": "video",
            "content_id": "vid_test_123",
            "title": "Test Video for Analytics",
            "tags": ["test", "analytics", "sparks"],
            "duration": 120,
        }

        return self.produce_message("content_posted", test_data)

    def test_engagement_activity(
        self, user_id: str = "testuser123", target_creator: str = "creator123"
    ):
        """Test: sparks.events.engagement_activity"""
        logger.info("❤️ Testing Engagement Activity Event")

        test_data = {
            "user_id": user_id,
            "username": "testuser",
            "action": "like",
            "target_user": target_creator,
            "target_content": "vid_test_123",
            "sparks": 5,
            "engagement_type": "video_like",
        }

        return self.produce_message("engagement_activity", test_data)

    # ============================================================================
    # TEST SCENARIOS - Advanced Flows
    # ============================================================================

    def test_milestone_flow(self, user_id: str = "milestoneuser"):
        """Test complete milestone achievement flow"""
        logger.info("🏆 Testing Milestone Achievement Flow")

        # Send sparks that should trigger 1000 sparks milestone
        success = self.test_user_sparks_update(user_id, sparks=1000)

        if success:
            logger.info("✅ Milestone flow initiated - check for milestone broadcasts!")
            time.sleep(2)  # Give time for processing

            # Follow up with notification
            self.test_notification_create(user_id)

        return success

    def test_new_user_journey(self, user_id: str = "journeyuser"):
        """Test complete new user onboarding journey"""
        logger.info("🌟 Testing New User Journey")

        # 1. User registers
        success1 = self.test_user_registered(user_id)
        time.sleep(1)

        # 2. User engages with content
        success2 = self.test_engagement_activity(user_id, "creator123")
        time.sleep(1)

        # 3. User earns first sparks
        success3 = self.test_user_sparks_update(user_id, sparks=100)

        return success1 and success2 and success3

    def test_creator_activity_flow(self, creator_id: str = "activecreatoor"):
        """Test creator activity and analytics flow"""
        logger.info("🎨 Testing Creator Activity Flow")

        # 1. Creator posts content
        success1 = self.test_content_posted(creator_id)
        time.sleep(1)

        # 2. Demographics get updated
        success2 = self.test_demographics_update(creator_id)
        time.sleep(1)

        # 3. Creator earns sparks from engagement
        success3 = self.test_user_sparks_update(creator_id, sparks=750)

        return success1 and success2 and success3

    # ============================================================================
    # BATCH TESTING
    # ============================================================================

    def run_all_tests(self):
        """Run all test scenarios"""
        logger.info("🚀 Starting comprehensive Kafka test suite...")

        tests = [
            ("User Sparks Update", lambda: self.test_user_sparks_update()),
            ("Notification Create", lambda: self.test_notification_create()),
            ("Demographics Update", lambda: self.test_demographics_update()),
            ("User Registered", lambda: self.test_user_registered()),
            ("Content Posted", lambda: self.test_content_posted()),
            ("Engagement Activity", lambda: self.test_engagement_activity()),
            ("Milestone Flow", lambda: self.test_milestone_flow()),
            ("New User Journey", lambda: self.test_new_user_journey()),
            ("Creator Activity Flow", lambda: self.test_creator_activity_flow()),
        ]

        results = []
        for test_name, test_func in tests:
            logger.info(f"\n{'='*60}")
            logger.info(f"Running: {test_name}")
            logger.info(f"{'='*60}")

            try:
                success = test_func()
                results.append((test_name, success))

                if success:
                    logger.info(f"✅ {test_name}: PASSED")
                else:
                    logger.error(f"❌ {test_name}: FAILED")

                time.sleep(3)  # Give time for processing between tests

            except Exception as e:
                logger.error(f"❌ {test_name}: ERROR - {e}")
                results.append((test_name, False))

        # Summary
        logger.info(f"\n{'='*60}")
        logger.info("TEST SUMMARY")
        logger.info(f"{'='*60}")

        passed = sum(1 for _, success in results if success)
        total = len(results)

        for test_name, success in results:
            status = "✅ PASSED" if success else "❌ FAILED"
            logger.info(f"{test_name}: {status}")

        logger.info(f"\nOverall: {passed}/{total} tests passed")

        if passed == total:
            logger.info(
                "🎉 All tests passed! Your Kafka integration is working correctly."
            )
        else:
            logger.warning(
                f"⚠️ {total - passed} tests failed. Check your consumer logs."
            )

    def test_high_volume(self, count: int = 100):
        """Test high volume message processing"""
        logger.info(f"🔥 Testing high volume: {count} messages")

        successful = 0
        for i in range(count):
            user_id = f"volume_user_{i}"
            success = self.test_user_sparks_update(user_id, sparks=10)
            if success:
                successful += 1

            if i % 10 == 0:
                logger.info(f"Progress: {i}/{count} messages sent")

            time.sleep(0.1)  # Small delay to avoid overwhelming

        logger.info(
            f"✅ High volume test complete: {successful}/{count} messages sent successfully"
        )

    def close(self):
        """Close producer connection"""
        if self.producer:
            self.producer.flush()
            logger.info("🔌 Producer connection closed")


def main():
    """Main function with CLI interface"""
    parser = argparse.ArgumentParser(description="Circo Sparks Kafka Test Producer")
    parser.add_argument(
        "--broker", default="localhost:9092", help="Kafka broker address"
    )
    parser.add_argument(
        "--test",
        choices=[
            "all",
            "sparks",
            "notification",
            "demographics",
            "user_registered",
            "content_posted",
            "engagement",
            "milestone",
            "journey",
            "creator",
            "volume",
        ],
        default="all",
        help="Which test to run",
    )
    parser.add_argument("--user-id", default="testuser123", help="User ID for tests")
    parser.add_argument(
        "--creator-id", default="creator123", help="Creator ID for tests"
    )
    parser.add_argument(
        "--sparks", type=int, default=500, help="Sparks amount for tests"
    )
    parser.add_argument(
        "--volume", type=int, default=100, help="Message count for volume test"
    )

    args = parser.parse_args()

    # Initialize producer
    producer = SparksTestProducer(kafka_broker=args.broker)

    try:
        logger.info(f"🔥 Starting Kafka test producer...")
        logger.info(f"📡 Broker: {args.broker}")
        logger.info(f"🧪 Test: {args.test}")

        # Run specific test
        if args.test == "all":
            producer.run_all_tests()
        elif args.test == "sparks":
            producer.test_user_sparks_update(args.user_id, args.sparks)
        elif args.test == "notification":
            producer.test_notification_create(args.user_id)
        elif args.test == "demographics":
            producer.test_demographics_update(args.creator_id)
        elif args.test == "user_registered":
            producer.test_user_registered(args.user_id)
        elif args.test == "content_posted":
            producer.test_content_posted(args.creator_id)
        elif args.test == "engagement":
            producer.test_engagement_activity(args.user_id, args.creator_id)
        elif args.test == "milestone":
            producer.test_milestone_flow(args.user_id)
        elif args.test == "journey":
            producer.test_new_user_journey(args.user_id)
        elif args.test == "creator":
            producer.test_creator_activity_flow(args.creator_id)
        elif args.test == "volume":
            producer.test_high_volume(args.volume)

        logger.info("🎉 Test producer finished successfully!")

    except KeyboardInterrupt:
        logger.info("⏹️ Test interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test producer error: {e}")
        sys.exit(1)
    finally:
        producer.close()


if __name__ == "__main__":
    main()


# Quick usage examples:

# Run all tests
# python test_producer.py --test all

# Test specific functionality
# python test_producer.py --test sparks --user-id john123 --sparks 1000

# Test milestone achievement (should trigger milestone detection)
# python test_producer.py --test milestone --user-id milestone_user

# Test new user journey
# python test_producer.py --test journey --user-id new_user_456

# Test high volume processing
# python test_producer.py --test volume --volume 500

# Test with different Kafka broker
# python test_producer.py --broker kafka.production.com:9092 --test all

# requirements_test.txt - Add this to your project
"""
confluent-kafka==2.3.0
"""

# docker-compose-test.yml - For local testing
"""
version: '3.8'
services:
  zookeeper:
    image: confluentinc/cp-zookeeper:7.4.0
    ports:
      - "2181:2181"
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181

  kafka:
    image: confluentinc/cp-kafka:7.4.0
    ports:
      - "9092:9092"
    depends_on:
      - zookeeper
    environment:
      KAFKA_BROKER_ID: 1
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://localhost:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1

  kafka-ui:
    image: provectuslabs/kafka-ui:latest
    ports:
      - "8080:8080"
    depends_on:
      - kafka
    environment:
      KAFKA_CLUSTERS_0_NAME: local
      KAFKA_CLUSTERS_0_BOOTSTRAPSERVERS: localhost:9092
"""

# test_scenarios.md - Test scenarios documentation
"""
# Kafka Test Scenarios

## 1. User Sparks Update Test
- Sends sparks update command
- Should trigger milestone detection if sparks >= 100, 500, 1000, etc.
- Should broadcast user_updated and milestone_achieved events

## 2. Notification Create Test
- Sends notification creation command
- Should broadcast notification_created event

## 3. Demographics Update Test
- Sends demographics update command
- Should broadcast demographics_updated event

## 4. User Registered Test
- Sends user registration event
- Should trigger welcome notification creation

## 5. Content Posted Test
- Sends content posted event
- Should update creator stats and broadcast

## 6. Engagement Activity Test
- Sends engagement event (like, comment, share)
- Should trigger sparks update for user

## 7. End-to-End Flows

### Milestone Achievement Flow
1. Send sparks update (1000+ sparks)
2. Verify milestone detection
3. Verify milestone broadcast
4. Verify notification creation

### New User Journey
1. User registration event
2. Welcome notification creation
3. First engagement activity
4. First sparks earned

### Creator Activity Flow
1. Content posted event
2. Demographics update
3. Sparks earned from engagement

## Expected Outputs (check consumer logs)
- ✅ Message received and processed
- ✅ Business logic executed
- ✅ Broadcast events emitted
- ✅ Database operations (if applicable)
"""
