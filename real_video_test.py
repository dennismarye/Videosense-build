#!/usr/bin/env python3
"""
Real Integration Testing for Enhanced Video Processing System
==========================================================

This script performs REAL testing with actual:
- Video downloads and processing
- Gemini AI API calls
- Quality analysis
- Slack notifications
- Full workflow testing

Usage: python real_video_test.py
"""

import asyncio
import json
import logging
import time
import os
import sys
from typing import Dict, Any, List
from pathlib import Path
import traceback
from datetime import datetime

# Add the src directory to Python path
sys.path.append(os.path.join(os.path.dirname(__file__), "src"))

from src.video_processor.video_processor import EnhancedVideoProcessor
from src.video_processor.s3_video_analyzer import S3VideoAnalyzer
from src.video_processor.google_generative_ai import EnhancedGoogleGenerativeService
from src.config.settings import settings

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(
            f"real_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

# Real test data with actual video URLs from production
REAL_TEST_VIDEOS = [
    {
        "name": "Comedy African Parents",
        "url": "https://s3.eu-west-2.amazonaws.com/prod.circleandclique.org/original-files/48ae92f8-e304-43e8-b60b-00dec6c7b9c8.mp4",
        "expected_categories": ["Comedy & Skits", "Entertainment & Gossip"],
        "circo_post": {
            "id": "6810a82febe3d79ad2b053db",
            "primaryCaption": "This had me rolling 😂😂 African parents be like... #comedy #funny #africanparents #viral",
            "jobId": "48ae92f8-e304-43e8-b60b-00dec6c7b9c8",
            "media": [
                {
                    "id": "48ae92f8-e304-43e8-b60b-00dec6c7b9c8",
                    "name": "comedy_video.mp4",
                    "fileType": "Video",
                    "original": "https://s3.eu-west-2.amazonaws.com/prod.circleandclique.org/original-files/48ae92f8-e304-43e8-b60b-00dec6c7b9c8.mp4",
                    "cachedOriginal": "https://s3.eu-west-2.amazonaws.com/prod.circleandclique.org/original-files/48ae92f8-e304-43e8-b60b-00dec6c7b9c8.mp4",
                }
            ],
        },
    },
    {
        "name": "Afrobeats Dance",
        "url": "https://d31plimlx9v8b3.cloudfront.net/meicam_1722429312169.mp4",
        "expected_categories": ["Music", "Entertainment & Gossip"],
        "circo_post": {
            "id": "6810a82febe3d79ad2b053dc",
            "primaryCaption": "New Afrobeats dance challenge! 🔥💃 Who's trying this? #afrobeats #dance #challenge #viral",
            "jobId": "a605cfcf-82dc-436f-939f-87d19ca4d100",
            "media": [
                {
                    "id": "a605cfcf-82dc-436f-939f-87d19ca4d100",
                    "name": "dance_video.mp4",
                    "fileType": "Video",
                    "original": "https://d31plimlx9v8b3.cloudfront.net/meicam_1722429312169.mp4",
                    "cachedOriginal": "https://d31plimlx9v8b3.cloudfront.net/meicam_1722429312169.mp4",
                }
            ],
        },
    },
    {
        "name": "Travel Lagos",
        "url": "https://s3.eu-west-2.amazonaws.com/prod.circleandclique.org/original-files/5a2b8c17-ca90-46e2-9c5b-80e024256e77.mp4",
        "expected_categories": ["Travel and Tourism", "Lifestyle & Culture"],
        "circo_post": {
            "id": "6810a82febe3d79ad2b053df",
            "primaryCaption": "Hidden gems of Lagos! 🌟 These spots will blow your mind #travel #lagos #nigeria #adventure #explore",
            "jobId": "5a2b8c17-ca90-46e2-9c5b-80e024256e77",
            "media": [
                {
                    "id": "5a2b8c17-ca90-46e2-9c5b-80e024256e77",
                    "name": "travel_video.mp4",
                    "fileType": "Video",
                    "original": "https://s3.eu-west-2.amazonaws.com/prod.circleandclique.org/original-files/5a2b8c17-ca90-46e2-9c5b-80e024256e77.mp4",
                    "cachedOriginal": "https://s3.eu-west-2.amazonaws.com/prod.circleandclique.org/original-files/5a2b8c17-ca90-46e2-9c5b-80e024256e77.mp4",
                }
            ],
        },
    },
]


class RealVideoTester:
    """Comprehensive real testing for video processing system"""

    def __init__(self):
        self.processor = None
        self.analyzer = None
        self.ai_service = None
        self.test_results = []
        self.failed_tests = []

    async def setup(self):
        """Initialize all services for real testing"""
        try:
            logger.info("🚀 Setting up Real Video Testing Environment...")

            # Initialize video processor
            self.processor = EnhancedVideoProcessor()
            logger.info("✅ Video Processor initialized")

            # Initialize video analyzer
            self.analyzer = S3VideoAnalyzer()
            logger.info("✅ Video Analyzer initialized")

            # Initialize AI service
            self.ai_service = EnhancedGoogleGenerativeService()
            logger.info("✅ AI Service initialized")

            # Verify all services are healthy
            await self.verify_service_health()

        except Exception as e:
            logger.error(f"❌ Setup failed: {e}")
            raise

    async def verify_service_health(self):
        """Verify all services are healthy and ready"""
        logger.info("🔍 Verifying service health...")

        # Check video processor health
        processor_health = self.processor.get_health_status()
        logger.info(f"Video Processor Health: {json.dumps(processor_health, indent=2)}")

        # Check AI service health
        ai_health = self.ai_service.get_health_status()
        logger.info(f"AI Service Health: {json.dumps(ai_health, indent=2)}")

        # Test AI connection with real API call
        try:
            ai_test = await self.ai_service.test_ai_connection()
            logger.info(f"AI Connection Test: {json.dumps(ai_test, indent=2)}")

            if ai_test.get("status") != "healthy":
                raise Exception(f"AI service unhealthy: {ai_test}")

        except Exception as e:
            logger.error(f"❌ AI service test failed: {e}")
            raise

        logger.info("✅ All services are healthy and ready")

    async def test_video_url_accessibility(
        self, video_url: str, video_name: str
    ) -> Dict[str, Any]:
        """Test if video URL is accessible and processable"""
        logger.info(f"🌐 Testing accessibility of: {video_name}")

        try:
            # Test with video analyzer
            validation = await self.processor.validate_video_accessibility(video_url)

            if validation.get("is_valid"):
                logger.info(f"✅ Video {video_name} is accessible and valid")
                return {"success": True, "validation": validation}
            else:
                logger.error(f"❌ Video {video_name} validation failed: {validation}")
                return {"success": False, "error": validation.get("error")}

        except Exception as e:
            logger.error(f"❌ Error testing video accessibility: {e}")
            return {"success": False, "error": str(e)}

    async def test_video_quality_analysis(
        self, video_url: str, video_name: str
    ) -> Dict[str, Any]:
        """Test real video quality analysis"""
        logger.info(f"📊 Testing quality analysis for: {video_name}")

        try:
            start_time = time.time()

            # Real quality analysis
            quality_result = await self.processor.analyze_video_quality(video_url)

            processing_time = time.time() - start_time

            logger.info(f"✅ Quality analysis completed in {processing_time:.2f}s")
            logger.info(f"Quality Result: {json.dumps(quality_result, indent=2)}")

            # Validate result structure
            required_fields = ["quality_score", "quality_level", "resolution", "fps"]
            missing_fields = [
                field for field in required_fields if field not in quality_result
            ]

            if missing_fields:
                logger.error(f"❌ Missing required fields: {missing_fields}")
                return {"success": False, "error": f"Missing fields: {missing_fields}"}

            return {
                "success": True,
                "result": quality_result,
                "processing_time": processing_time,
            }

        except Exception as e:
            logger.error(f"❌ Quality analysis failed: {e}")
            return {"success": False, "error": str(e)}

    async def test_video_download_and_processing(
        self, video_url: str, job_id: str, video_name: str
    ) -> Dict[str, Any]:
        """Test real video download and processing with FFmpeg"""
        logger.info(f"⬇️ Testing video download and processing for: {video_name}")

        try:
            start_time = time.time()

            # Real video download and processing
            processed_path = await self.processor.download_and_process_video(
                video_url, job_id
            )

            processing_time = time.time() - start_time

            if processed_path and os.path.exists(processed_path):
                file_size = os.path.getsize(processed_path)
                logger.info(
                    f"✅ Video processed successfully in {processing_time:.2f}s"
                )
                logger.info(f"Processed file: {processed_path} ({file_size} bytes)")

                return {
                    "success": True,
                    "processed_path": processed_path,
                    "file_size": file_size,
                    "processing_time": processing_time,
                }
            else:
                logger.error(f"❌ Video processing failed - no output file")
                return {"success": False, "error": "No output file generated"}

        except Exception as e:
            logger.error(f"❌ Video download/processing failed: {e}")
            return {"success": False, "error": str(e)}

    async def test_ai_safety_and_tagging(
        self, circo_post: Dict[str, Any], processed_path: str, video_name: str
    ) -> Dict[str, Any]:
        """Test real AI safety check and tagging with Gemini"""
        logger.info(f"🤖 Testing AI safety and tagging for: {video_name}")

        try:
            start_time = time.time()

            # Real AI analysis with Gemini
            ai_result = await self.ai_service.analyze_video_safety_and_tags(
                processed_path, circo_post
            )

            processing_time = time.time() - start_time

            logger.info(f"✅ AI analysis completed in {processing_time:.2f}s")
            logger.info(f"AI Result: {json.dumps(ai_result, indent=2)}")

            # Validate result structure
            required_fields = ["safety_check", "tags", "aiContext"]
            missing_fields = [
                field for field in required_fields if field not in ai_result
            ]

            if missing_fields:
                logger.error(f"❌ Missing required fields: {missing_fields}")
                return {"success": False, "error": f"Missing fields: {missing_fields}"}

            # Validate safety check
            safety_check = ai_result.get("safety_check", {})
            content_flag = safety_check.get("contentFlag")

            if content_flag not in ["SAFE", "RESTRICT_18+", "BLOCK_VIOLATION"]:
                logger.error(f"❌ Invalid content flag: {content_flag}")
                return {
                    "success": False,
                    "error": f"Invalid content flag: {content_flag}",
                }

            return {
                "success": True,
                "result": ai_result,
                "processing_time": processing_time,
                "content_flag": content_flag,
                "tags_count": len(ai_result.get("tags", [])),
            }

        except Exception as e:
            logger.error(f"❌ AI analysis failed: {e}")
            return {"success": False, "error": str(e)}

    async def test_description_alignment(
        self, user_caption: str, ai_context: str, video_name: str
    ) -> Dict[str, Any]:
        """Test real description alignment analysis"""
        logger.info(f"📝 Testing description alignment for: {video_name}")

        try:
            start_time = time.time()

            # Real description alignment analysis
            alignment_result = await self.ai_service.analyze_description_alignment(
                user_caption, ai_context
            )

            processing_time = time.time() - start_time

            logger.info(f"✅ Description alignment completed in {processing_time:.2f}s")
            logger.info(f"Alignment Result: {json.dumps(alignment_result, indent=2)}")

            # Validate result structure
            required_fields = ["alignmentScore", "alignmentLevel", "justification"]
            missing_fields = [
                field for field in required_fields if field not in alignment_result
            ]

            if missing_fields:
                logger.error(f"❌ Missing required fields: {missing_fields}")
                return {"success": False, "error": f"Missing fields: {missing_fields}"}

            return {
                "success": True,
                "result": alignment_result,
                "processing_time": processing_time,
            }

        except Exception as e:
            logger.error(f"❌ Description alignment failed: {e}")
            return {"success": False, "error": str(e)}

    async def test_slack_notification(
        self,
        ai_result: Dict[str, Any],
        video_info: Dict[str, Any],
        circo_post: Dict[str, Any],
        video_name: str,
    ) -> Dict[str, Any]:
        """Test real Slack notification"""
        logger.info(f"📢 Testing Slack notification for: {video_name}")

        try:
            # Real Slack notification
            await self.ai_service.send_safety_notification(
                ai_result, video_info, circo_post
            )

            logger.info(f"✅ Slack notification sent successfully for {video_name}")
            return {"success": True}

        except Exception as e:
            logger.error(f"❌ Slack notification failed: {e}")
            return {"success": False, "error": str(e)}

    async def test_full_workflow(self, test_video: Dict[str, Any]) -> Dict[str, Any]:
        """Test complete end-to-end workflow for a video"""
        video_name = test_video["name"]
        video_url = test_video["url"]
        circo_post = test_video["circo_post"]
        job_id = circo_post["jobId"]

        logger.info(f"🎬 Starting full workflow test for: {video_name}")
        logger.info(f"Video URL: {video_url}")

        workflow_results = {
            "video_name": video_name,
            "video_url": video_url,
            "job_id": job_id,
            "start_time": datetime.now().isoformat(),
            "tests": {},
        }

        try:
            # Step 1: Test video accessibility
            logger.info(f"Step 1: Testing video accessibility...")
            accessibility_result = await self.test_video_url_accessibility(
                video_url, video_name
            )
            workflow_results["tests"]["accessibility"] = accessibility_result

            if not accessibility_result["success"]:
                logger.error(f"❌ Workflow stopped - video not accessible")
                return workflow_results

            # Step 2: Test quality analysis
            logger.info(f"Step 2: Testing quality analysis...")
            quality_result = await self.test_video_quality_analysis(
                video_url, video_name
            )
            workflow_results["tests"]["quality_analysis"] = quality_result

            # Step 3: Test video download and processing
            logger.info(f"Step 3: Testing video download and processing...")
            download_result = await self.test_video_download_and_processing(
                video_url, job_id, video_name
            )
            workflow_results["tests"]["download_processing"] = download_result

            if not download_result["success"]:
                logger.error(f"❌ Workflow stopped - video processing failed")
                return workflow_results

            processed_path = download_result["processed_path"]

            # Step 4: Test AI safety and tagging
            logger.info(f"Step 4: Testing AI safety and tagging...")
            ai_result = await self.test_ai_safety_and_tagging(
                circo_post, processed_path, video_name
            )
            workflow_results["tests"]["ai_analysis"] = ai_result

            if not ai_result["success"]:
                logger.error(f"❌ Workflow stopped - AI analysis failed")
                return workflow_results

            ai_context = ai_result["result"]["aiContext"]
            user_caption = circo_post["primaryCaption"]

            # Step 5: Test description alignment
            logger.info(f"Step 5: Testing description alignment...")
            alignment_result = await self.test_description_alignment(
                user_caption, ai_context, video_name
            )
            workflow_results["tests"]["description_alignment"] = alignment_result

            # Step 6: Test Slack notification
            logger.info(f"Step 6: Testing Slack notification...")
            video_info = {"name": video_name, "url": video_url, "id": job_id}
            slack_result = await self.test_slack_notification(
                ai_result["result"], video_info, circo_post, video_name
            )
            workflow_results["tests"]["slack_notification"] = slack_result

            # Clean up processed file
            try:
                if os.path.exists(processed_path):
                    os.remove(processed_path)
                    logger.info(f"🗑️ Cleaned up processed file: {processed_path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not clean up file: {e}")

            # Calculate overall success
            all_tests_passed = all(
                test.get("success", False)
                for test in workflow_results["tests"].values()
            )
            workflow_results["overall_success"] = all_tests_passed
            workflow_results["end_time"] = datetime.now().isoformat()

            if all_tests_passed:
                logger.info(f"✅ Full workflow test PASSED for {video_name}")
            else:
                logger.error(f"❌ Full workflow test FAILED for {video_name}")

            return workflow_results

        except Exception as e:
            logger.error(f"❌ Workflow test failed with exception: {e}")
            logger.error(traceback.format_exc())
            workflow_results["tests"]["workflow_exception"] = {
                "success": False,
                "error": str(e),
            }
            workflow_results["overall_success"] = False
            return workflow_results

    async def run_all_tests(self):
        """Run comprehensive tests on all videos"""
        logger.info("🚀 Starting comprehensive real video testing...")

        all_results = {
            "test_session": {
                "start_time": datetime.now().isoformat(),
                "total_videos": len(REAL_TEST_VIDEOS),
                "environment": os.getenv("NODE_ENV", "development"),
            },
            "videos": [],
        }

        for i, test_video in enumerate(REAL_TEST_VIDEOS, 1):
            logger.info(f"\n{'='*80}")
            logger.info(
                f"🎥 Testing Video {i}/{len(REAL_TEST_VIDEOS)}: {test_video['name']}"
            )
            logger.info(f"{'='*80}")

            try:
                workflow_result = await self.test_full_workflow(test_video)
                all_results["videos"].append(workflow_result)

                if workflow_result["overall_success"]:
                    self.test_results.append(workflow_result)
                    logger.info(f"✅ Video {i} PASSED: {test_video['name']}")
                else:
                    self.failed_tests.append(workflow_result)
                    logger.error(f"❌ Video {i} FAILED: {test_video['name']}")

            except Exception as e:
                logger.error(f"❌ Video {i} CRASHED: {test_video['name']} - {e}")
                failure_result = {
                    "video_name": test_video["name"],
                    "overall_success": False,
                    "error": str(e),
                    "exception": traceback.format_exc(),
                }
                all_results["videos"].append(failure_result)
                self.failed_tests.append(failure_result)

        # Calculate final results
        total_tests = len(REAL_TEST_VIDEOS)
        passed_tests = len(self.test_results)
        failed_tests = len(self.failed_tests)

        all_results["test_session"]["end_time"] = datetime.now().isoformat()
        all_results["summary"] = {
            "total": total_tests,
            "passed": passed_tests,
            "failed": failed_tests,
            "success_rate": (
                f"{(passed_tests/total_tests)*100:.1f}%" if total_tests > 0 else "0%"
            ),
        }

        # Log final summary
        logger.info(f"\n{'='*80}")
        logger.info(f"🏁 FINAL TEST RESULTS")
        logger.info(f"{'='*80}")
        logger.info(f"Total Videos Tested: {total_tests}")
        logger.info(f"✅ Passed: {passed_tests}")
        logger.info(f"❌ Failed: {failed_tests}")
        logger.info(f"Success Rate: {all_results['summary']['success_rate']}")

        if failed_tests > 0:
            logger.info(f"\n❌ Failed Tests:")
            for failure in self.failed_tests:
                logger.info(
                    f"  - {failure.get('video_name', 'Unknown')}: {failure.get('error', 'Unknown error')}"
                )

        # Save detailed results to file
        results_file = (
            f"real_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        with open(results_file, "w") as f:
            json.dump(all_results, f, indent=2)

        logger.info(f"📄 Detailed results saved to: {results_file}")

        return all_results


async def main():
    """Main function to run real tests"""
    print("🎬 Enhanced Video Processing - Real Integration Tests")
    print("=" * 60)

    # Check environment variables
    required_env_vars = ["GEMINI_KEY", "SLACK_BOT_TOKEN"]
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]

    if missing_vars:
        print(f"❌ Missing required environment variables: {missing_vars}")
        print("Please set these variables before running the tests.")
        return

    tester = RealVideoTester()

    try:
        # Setup
        await tester.setup()

        # Run all tests
        results = await tester.run_all_tests()

        # Print summary
        print(f"\n🏁 Testing Complete!")
        print(f"Success Rate: {results['summary']['success_rate']}")

        if results["summary"]["failed"] == 0:
            print(
                "🎉 All tests passed! Your video processing system is working perfectly."
            )
        else:
            print(
                f"⚠️ {results['summary']['failed']} tests failed. Check the logs for details."
            )

    except Exception as e:
        print(f"❌ Test setup failed: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    # Run the real tests
    asyncio.run(main())
