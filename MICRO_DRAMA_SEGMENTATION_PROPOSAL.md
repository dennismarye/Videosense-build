# Micro Drama Video Segmentation Feature - Technical Proposal

**Prepared for:** CTO
**Prepared by:** Engineering Team
**Date:** December 8, 2025
**Project:** California Company - Nigeria Micro Drama Launch (Feb 19, 2025)

---

## Executive Summary

This proposal outlines the technical architecture for implementing automated video segmentation to transform long-form content (3+ hours) into 90-second micro drama episodes. The system will leverage Gemini AI for intelligent title and description generation, MoviePy for precise video cutting, and AWS S3 for segment storage.

**Key Requirements:**
- Break long-form videos into sequential 90-second episodes
- Generate AI-powered episode titles and descriptions
- Upload segments to S3 with organized metadata
- Communicate processed segments to file-service
- Support 3+ hour video uploads
- Launch date: February 19, 2025

---

## Service Architecture Recommendation

### **Option A: Extend Existing `video_tagging_service` (RECOMMENDED)**

**Reasoning:**
- Service already handles Kafka-based video processing
- Has established Gemini AI integration
- Includes S3 infrastructure (boto3, AWS credentials)
- Contains FFmpeg integration for video processing
- Production-ready with monitoring, health checks, and error handling

**Implementation Approach:**
Add a new dedicated microservice module within the existing service:
```
src/
  └── video_segmentation/
      ├── __init__.py
      ├── segment_processor.py      # Core segmentation logic
      ├── gemini_titling_service.py # Episode title/description generation
      └── s3_segment_uploader.py    # S3 upload orchestration
```

**Pros:**
- Faster time-to-market (reuse existing infrastructure)
- Single deployment pipeline
- Shared monitoring and logging
- Consistent error handling patterns
- Lower operational overhead

**Cons:**
- Service becomes more complex (multiple responsibilities)
- Potential resource contention if both workflows run simultaneously
- Requires careful separation of concerns

---

### **Option B: Create New Standalone Service**

**Reasoning:**
- Clear separation of concerns (segmentation vs. classification)
- Independent scaling and deployment
- Dedicated resources for long video processing

**Pros:**
- Service isolation
- Independent scaling
- Clearer domain boundaries
- Easier to debug and maintain

**Cons:**
- Slower time-to-market
- Duplicate infrastructure code
- Additional deployment complexity
- More operational overhead
- Need to set up monitoring, Kafka, S3, Gemini from scratch

---

## Recommended Approach: **Option A - Extend Existing Service**

Given the tight timeline (Feb 19, 2025) and existing infrastructure, extending the current service is optimal.

---

## Technical Implementation Design

### 1. High-Level Workflow

```
┌─────────────────────┐
│  Creator Uploads    │
│  Full Video (3+ hrs)│
│  to Platform        │
└──────────┬──────────┘
           │
           ▼
┌─────────────────────────────────────────────┐
│         File Service                        │
│  - Validates upload (size, format)          │
│  - Stores original video in S3              │
│  - Publishes to Kafka topic:                │
│    "segmentation.video_uploaded"            │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│    Video Segmentation Service (Kafka)      │
│  - Consumes: segmentation.video_uploaded   │
│  - Downloads original video from S3         │
│  - Segments into 90-second clips            │
│  - Generates titles/descriptions (Gemini)   │
│  - Uploads segments to S3                   │
│  - Publishes results to Kafka topic:        │
│    "segmentation.segments_ready"            │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────┐
│         File Service                        │
│  - Receives segment metadata                │
│  - Updates database with episodes           │
│  - Triggers preview interface display       │
│  - Notifies creator for review/approval     │
└─────────────────────────────────────────────┘
```

---

### 2. Video Segmentation Pipeline

#### **Stage 1: Video Download & Validation**

**Purpose:** Download full video from S3 and validate processiblity

**Key Operations:**
1. Receive Kafka message with video metadata:
   ```json
   {
     "jobId": "seg-12345",
     "videoId": "video-98765",
     "originalVideoUrl": "s3://bucket/uploads/drama-full.mp4",
     "bucket": "circo-video-uploads",
     "key": "uploads/drama-full.mp4",
     "duration": 10800,
     "fileSize": 5368709120,
     "uploadedBy": "creator-456",
     "requestedSegmentDuration": 90
   }
   ```

2. Download video from S3 to local temp directory
3. Validate video integrity using MoviePy
4. Extract video metadata (duration, resolution, codec)

**Technology:**
- **boto3:** S3 download with progress tracking
- **MoviePy:** Video validation and metadata extraction

**Error Handling:**
- Video corrupted → Publish failure to Kafka, notify file-service
- Unsupported format → Convert using FFmpeg before processing
- Download timeout → Retry with exponential backoff (3 attempts)

---

#### **Stage 2: Sequential Video Segmentation**

**Purpose:** Cut video into 90-second episodes using precise frame boundaries

**Algorithm:**
```python
# Pseudo-code for segmentation logic

video_duration = get_video_duration(video_path)  # e.g., 10800 seconds (3 hours)
segment_duration = 90  # seconds
total_segments = math.ceil(video_duration / segment_duration)  # e.g., 120 episodes

segments = []
for i in range(total_segments):
    start_time = i * segment_duration
    end_time = min((i + 1) * segment_duration, video_duration)

    segment = {
        "episodeNumber": i + 1,
        "startTime": start_time,
        "endTime": end_time,
        "duration": end_time - start_time
    }

    # Cut video segment
    segment_path = cut_video_segment(video_path, start_time, end_time, episode_number=i+1)

    segment["localPath"] = segment_path
    segments.append(segment)

return segments
```

**MoviePy Implementation:**
```python
from moviepy.editor import VideoFileClip
import os

def cut_video_segment(source_video_path, start_time, end_time, episode_number, output_dir):
    """
    Cut a specific segment from the source video

    Args:
        source_video_path: Path to the full video file
        start_time: Start time in seconds
        end_time: End time in seconds
        episode_number: Episode number (for file naming)
        output_dir: Directory to save segments

    Returns:
        Path to the generated segment file
    """
    try:
        # Load video
        video = VideoFileClip(source_video_path)

        # Extract subclip
        segment = video.subclip(start_time, end_time)

        # Generate output filename
        segment_filename = f"episode_{episode_number:03d}.mp4"
        segment_path = os.path.join(output_dir, segment_filename)

        # Write segment with optimized codec settings
        segment.write_videofile(
            segment_path,
            codec='libx264',
            audio_codec='aac',
            temp_audiofile='temp-audio.m4a',
            remove_temp=True,
            fps=video.fps,
            preset='medium',
            threads=4
        )

        # Cleanup
        video.close()
        segment.close()

        return segment_path

    except Exception as e:
        logging.error(f"Error cutting segment {episode_number}: {e}")
        raise
```

**Key Considerations:**
- **Frame Accuracy:** Use MoviePy's subclip() for precise frame boundaries
- **Codec Consistency:** Maintain original video codec (or standardize to H.264)
- **Last Episode Handling:** Final episode may be shorter than 90 seconds
- **Memory Management:** Process one segment at a time, close VideoFileClip after each cut
- **Temp Storage:** Store segments in `/tmp/segments/{jobId}/` during processing

**Performance Optimization:**
- Use MoviePy's threading for faster encoding
- Process segments sequentially (not parallel) to avoid memory overflow
- Clean up each segment from local storage after S3 upload

---

#### **Stage 3: AI-Powered Title & Description Generation**

**Purpose:** Generate contextually relevant titles and descriptions for each episode using Gemini AI

**Gemini Integration Strategy:**

**Option 3A: Frame-Based Analysis (RECOMMENDED for Cost Efficiency)**
```python
async def generate_episode_metadata_from_frames(segment_path, episode_number, total_episodes, previous_context=""):
    """
    Generate title and description using video frames from the segment

    Args:
        segment_path: Path to the 90-second segment
        episode_number: Current episode number
        total_episodes: Total number of episodes
        previous_context: Summary from previous episode (for continuity)

    Returns:
        dict: {"title": "...", "description": "...", "aiContext": "..."}
    """

    # Extract 3 representative frames from the segment (beginning, middle, end)
    frames = extract_key_frames(segment_path, num_frames=3)

    # Upload frames to Gemini
    frame_files = [genai.upload_file(frame_path) for frame_path in frames]

    # Wait for processing
    for frame_file in frame_files:
        while frame_file.state.name == "PROCESSING":
            await asyncio.sleep(2)
            frame_file = genai.get_file(frame_file.name)

    # Gemini prompt for episode titling
    prompt = f"""
You are an expert content strategist for a micro drama streaming platform. Analyze the provided frames from Episode {episode_number} of {total_episodes} and generate:

1. **Episode Title:** A compelling, concise title (5-8 words) that captures the essence of this episode
2. **Episode Description:** A 2-3 sentence description that entices viewers and provides context

Context from Previous Episode:
{previous_context if previous_context else "This is the first episode."}

Requirements:
- Title should be engaging and hint at the episode's content
- Description should create curiosity for the next episode
- Maintain narrative continuity with previous episodes
- Use Nigerian cultural context where applicable
- Keep titles suitable for mobile display

Output Format (JSON only):
{{
  "title": "Episode title here",
  "description": "Compelling description here",
  "aiContext": "One-sentence summary of this episode's key events for the next episode's context"
}}
"""

    model = genai.GenerativeModel(model_name="gemini-2.5-flash")
    response = model.generate_content(
        [*frame_files, prompt],
        request_options={"timeout": 180}
    )

    result = await extract_json_from_response(response.text)

    # Cleanup frames
    for frame_path in frames:
        os.remove(frame_path)

    return result
```

**Option 3B: Video Segment Upload (Higher Quality, Higher Cost)**
```python
async def generate_episode_metadata_from_video(segment_path, episode_number, total_episodes, previous_context=""):
    """
    Generate title and description by uploading the full 90-second segment to Gemini

    Note: More accurate but uses more Gemini API quota
    """

    # Upload segment to Gemini
    video_file = genai.upload_file(segment_path)

    # Wait for processing
    while video_file.state.name == "PROCESSING":
        await asyncio.sleep(10)
        video_file = genai.get_file(video_file.name)

    # Same prompt as Option 3A
    prompt = get_episode_titling_prompt(episode_number, total_episodes, previous_context)

    model = genai.GenerativeModel(model_name="gemini-2.5-flash")
    response = model.generate_content(
        [video_file, prompt],
        request_options={"timeout": 300}
    )

    result = await extract_json_from_response(response.text)
    return result
```

**Recommended Approach:** **Option 3A (Frame-Based)**
- Faster processing (no video upload wait time)
- Lower API costs
- Sufficient quality for title/description generation
- Extract frames at 0%, 50%, 100% of segment duration

**Gemini Rate Limiting:**
- Process episodes sequentially (not parallel) to avoid rate limits
- Implement retry logic with exponential backoff
- Monitor Gemini quota usage

**Contextual Continuity:**
- Pass `aiContext` from Episode N to Episode N+1
- This ensures narrative consistency across episodes
- Example: Episode 2 knows that Episode 1 was about "protagonist discovering a secret"

---

#### **Stage 4: S3 Upload & Metadata Organization**

**Purpose:** Upload segmented videos to S3 with organized structure and metadata

**S3 Bucket Structure:**
```
s3://circo-micro-dramas/
  └── {dramaId}/
      ├── original/
      │   └── full-video.mp4                  # Original upload
      ├── segments/
      │   ├── episode_001.mp4
      │   ├── episode_002.mp4
      │   ├── ...
      │   └── episode_120.mp4
      └── metadata/
          ├── manifest.json                    # Master manifest
          └── episodes/
              ├── episode_001.json
              ├── episode_002.json
              └── ...
```

**Upload Implementation:**
```python
import boto3
import json
from typing import Dict, List

class S3SegmentUploader:
    def __init__(self, bucket_name, aws_access_key, aws_secret_key, region):
        self.s3_client = boto3.client(
            's3',
            aws_access_key_id=aws_access_key,
            aws_secret_access_key=aws_secret_key,
            region_name=region
        )
        self.bucket_name = bucket_name

    async def upload_segment(self, segment_path, drama_id, episode_number, metadata):
        """
        Upload a single episode segment to S3

        Args:
            segment_path: Local path to segment file
            drama_id: Unique drama identifier
            episode_number: Episode number
            metadata: Episode metadata (title, description, etc.)

        Returns:
            dict: Upload result with S3 URLs
        """
        try:
            # S3 keys
            video_key = f"{drama_id}/segments/episode_{episode_number:03d}.mp4"
            metadata_key = f"{drama_id}/metadata/episodes/episode_{episode_number:03d}.json"

            # Upload video file
            self.s3_client.upload_file(
                segment_path,
                self.bucket_name,
                video_key,
                ExtraArgs={
                    'ContentType': 'video/mp4',
                    'Metadata': {
                        'drama-id': drama_id,
                        'episode-number': str(episode_number),
                        'title': metadata.get('title', ''),
                        'duration': str(metadata.get('duration', 90))
                    }
                }
            )

            # Upload metadata JSON
            metadata_json = {
                "dramaId": drama_id,
                "episodeNumber": episode_number,
                "title": metadata.get("title"),
                "description": metadata.get("description"),
                "duration": metadata.get("duration"),
                "videoUrl": f"s3://{self.bucket_name}/{video_key}",
                "startTime": metadata.get("startTime"),
                "endTime": metadata.get("endTime"),
                "aiContext": metadata.get("aiContext"),
                "uploadedAt": time.time()
            }

            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=metadata_key,
                Body=json.dumps(metadata_json, indent=2),
                ContentType='application/json'
            )

            # Generate presigned URLs (valid for 7 days for preview)
            video_presigned_url = self.s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': self.bucket_name, 'Key': video_key},
                ExpiresIn=604800  # 7 days
            )

            return {
                "success": True,
                "videoKey": video_key,
                "metadataKey": metadata_key,
                "videoUrl": f"s3://{self.bucket_name}/{video_key}",
                "presignedUrl": video_presigned_url,
                "metadata": metadata_json
            }

        except Exception as e:
            logging.error(f"Error uploading segment {episode_number}: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def create_manifest(self, drama_id, episodes_metadata, original_video_metadata):
        """
        Create master manifest file for the entire drama series

        Args:
            drama_id: Unique drama identifier
            episodes_metadata: List of all episode metadata
            original_video_metadata: Metadata about the original video

        Returns:
            dict: Manifest upload result
        """
        manifest = {
            "dramaId": drama_id,
            "totalEpisodes": len(episodes_metadata),
            "createdAt": time.time(),
            "originalVideo": original_video_metadata,
            "episodes": episodes_metadata,
            "segmentationSettings": {
                "segmentDuration": 90,
                "method": "sequential",
                "aiModel": "gemini-2.5-flash"
            }
        }

        manifest_key = f"{drama_id}/metadata/manifest.json"

        self.s3_client.put_object(
            Bucket=self.bucket_name,
            Key=manifest_key,
            Body=json.dumps(manifest, indent=2),
            ContentType='application/json'
        )

        return {
            "success": True,
            "manifestKey": manifest_key,
            "manifestUrl": f"s3://{self.bucket_name}/{manifest_key}"
        }
```

**Upload Optimization:**
- Use boto3's upload_file() for automatic multipart upload (large files)
- Upload video and metadata in parallel (asyncio.gather)
- Implement retry logic for failed uploads
- Generate presigned URLs for preview interface

---

#### **Stage 5: Communication with File Service**

**Purpose:** Notify file-service that segmentation is complete and provide episode data

**Kafka Message Structure:**
```json
{
  "event": "segmentation_completed",
  "jobId": "seg-12345",
  "dramaId": "drama-98765",
  "status": "success",
  "processingTime": 3600,
  "originalVideo": {
    "videoId": "video-98765",
    "duration": 10800,
    "url": "s3://bucket/drama-98765/original/full-video.mp4"
  },
  "segmentation": {
    "totalEpisodes": 120,
    "segmentDuration": 90,
    "manifestUrl": "s3://bucket/drama-98765/metadata/manifest.json"
  },
  "episodes": [
    {
      "episodeNumber": 1,
      "title": "The Secret Letter Arrives",
      "description": "A mysterious letter sets off a chain of events that will change everything. Who sent it and what do they want?",
      "duration": 90,
      "videoUrl": "s3://bucket/drama-98765/segments/episode_001.mp4",
      "presignedUrl": "https://s3.amazonaws.com/...",
      "metadataUrl": "s3://bucket/drama-98765/metadata/episodes/episode_001.json",
      "startTime": 0,
      "endTime": 90
    },
    {
      "episodeNumber": 2,
      "title": "Uncovering Hidden Truths",
      "description": "The protagonist digs deeper into the mystery, discovering shocking revelations about their past.",
      "duration": 90,
      "videoUrl": "s3://bucket/drama-98765/segments/episode_002.mp4",
      "presignedUrl": "https://s3.amazonaws.com/...",
      "metadataUrl": "s3://bucket/drama-98765/metadata/episodes/episode_002.json",
      "startTime": 90,
      "endTime": 180
    }
    // ... remaining 118 episodes
  ],
  "timestamp": 1704729600
}
```

**Kafka Topic:** `segmentation.segments_ready`

**File Service Actions:**
1. Receive Kafka message
2. Store episode metadata in database
3. Create drama series entry with episodes
4. Generate preview interface for creator review
5. Send notification to creator

---

### 3. Error Handling & Recovery

**Failure Scenarios:**

| Scenario | Detection | Recovery Strategy |
|----------|-----------|-------------------|
| Video download fails | S3 download timeout/error | Retry 3x with exponential backoff, then fail job |
| Segmentation fails mid-process | MoviePy exception during cut | Save progress, resume from last successful segment |
| Gemini API rate limit | 429 response from Gemini | Exponential backoff retry, queue remaining episodes |
| S3 upload fails | boto3 upload exception | Retry 3x, if fails, mark segment as failed in manifest |
| Kafka publish fails | Kafka producer timeout | Store in local retry queue, attempt republish every 30s |
| Out of disk space | OSError during segment save | Clean up processed segments, fail job gracefully |

**Partial Failure Handling:**
```python
# If 100 out of 120 episodes succeed, still publish results with failure annotations

{
  "status": "partial_success",
  "successfulEpisodes": 100,
  "failedEpisodes": [
    {
      "episodeNumber": 45,
      "error": "Gemini API timeout",
      "retryable": true
    },
    {
      "episodeNumber": 78,
      "error": "S3 upload failed",
      "retryable": true
    }
    // ... 18 more failures
  ]
}
```

**Manual Retry Mechanism:**
- File-service can trigger retry for specific episodes
- Segmentation service maintains retry queue
- Failed episodes can be reprocessed without re-segmenting entire video

---

### 4. Configuration & Environment Variables

**New Settings Required (add to `src/config/settings.py`):**

```python
# Video Segmentation Configuration
ENABLE_VIDEO_SEGMENTATION: bool = True
SEGMENT_DURATION_SECONDS: int = 90
MAX_VIDEO_UPLOAD_SIZE_MB: int = 10240  # 10GB (for 3+ hour videos)
SEGMENTATION_TEMP_DIR: str = "/tmp/video_segmentation"
SEGMENTATION_OUTPUT_BUCKET: str = "circo-micro-dramas"

# Kafka Topics for Segmentation
SEGMENTATION_INPUT_TOPIC: str = "segmentation.video_uploaded"
SEGMENTATION_OUTPUT_TOPIC: str = "segmentation.segments_ready"

# Gemini Configuration for Titling
GEMINI_TITLING_MODEL: str = "gemini-2.5-flash"
GEMINI_TITLING_TIMEOUT: int = 180
GEMINI_MAX_FRAMES_PER_EPISODE: int = 3

# MoviePy Configuration
MOVIEPY_THREADS: int = 4
MOVIEPY_CODEC: str = "libx264"
MOVIEPY_AUDIO_CODEC: str = "aac"
MOVIEPY_PRESET: str = "medium"  # ultrafast, fast, medium, slow

# S3 Upload Configuration
S3_SEGMENT_PRESIGNED_EXPIRY: int = 604800  # 7 days
S3_MULTIPART_THRESHOLD: int = 104857600  # 100MB
S3_MULTIPART_CHUNKSIZE: int = 10485760   # 10MB
```

---

### 5. Performance Considerations

**Processing Time Estimates (3-hour video = 10,800 seconds = 120 episodes):**

| Stage | Time per Episode | Total Time (120 episodes) | Notes |
|-------|------------------|--------------------------|-------|
| Download Original | - | 5-10 minutes | One-time, depends on file size |
| Segmentation (MoviePy) | 5-10 seconds | 10-20 minutes | Sequential processing |
| Frame Extraction | 2-3 seconds | 4-6 minutes | 3 frames per episode |
| Gemini Titling | 10-15 seconds | 20-30 minutes | Includes API wait time |
| S3 Upload | 3-5 seconds | 6-10 minutes | Parallel uploads |
| Kafka Publish | 1 second | 2 minutes | Batch publish |
| **Total** | - | **~50-80 minutes** | End-to-end pipeline |

**Optimization Strategies:**
1. **Parallel Frame Extraction:** Extract frames for multiple episodes simultaneously
2. **Batch Gemini Requests:** Process 5-10 episodes in parallel (respect rate limits)
3. **Async S3 Uploads:** Upload segments while processing next segment
4. **Resource Allocation:** Dedicate 8GB RAM, 4 CPU cores for segmentation service

**Scaling for Multiple Concurrent Dramas:**
- Use Kafka consumer groups for horizontal scaling
- Each instance processes one drama at a time
- Queue additional dramas in Kafka topic

---

### 6. Dependencies & Technology Stack

**New Python Dependencies (add to `requirements.txt`):**
```
moviepy==1.0.3
imageio==2.34.0
imageio-ffmpeg==0.4.9
Pillow==11.1.0  # (already included)
```

**System Dependencies:**
```bash
# FFmpeg (required by MoviePy)
apt-get install ffmpeg
# or
brew install ffmpeg

# Increased temp storage
# Ensure /tmp has at least 50GB available for 3-hour video processing
```

**Technology Stack:**
- **Video Processing:** MoviePy (Python wrapper for FFmpeg)
- **AI Titling:** Google Gemini 2.5 Flash (already integrated)
- **Storage:** AWS S3 with boto3 (already integrated)
- **Messaging:** Apache Kafka (already integrated)
- **Frame Extraction:** MoviePy + Pillow

---

### 7. Testing Strategy

**Unit Tests:**
```python
# tests/test_video_segmentation.py

async def test_video_segmentation_90_second_cuts():
    """Test that videos are cut at exact 90-second boundaries"""
    segment = cut_video_segment("test_video.mp4", 0, 90, 1, "/tmp")
    duration = get_video_duration(segment)
    assert 89 <= duration <= 91  # Allow 1-second tolerance

async def test_last_episode_handling():
    """Test that final episode handles remaining duration correctly"""
    # Video is 275 seconds (3 episodes: 90, 90, 95)
    segments = segment_video("test_275s.mp4", 90)
    assert len(segments) == 4
    assert segments[-1]["duration"] == 5

async def test_gemini_title_generation():
    """Test that Gemini generates valid titles and descriptions"""
    result = await generate_episode_metadata_from_frames("segment.mp4", 1, 120)
    assert "title" in result
    assert "description" in result
    assert len(result["title"]) <= 50  # Mobile-friendly length
```

**Integration Tests:**
```python
async def test_end_to_end_segmentation():
    """Test full pipeline from download to Kafka publish"""
    # Simulate Kafka message
    message = {
        "jobId": "test-job",
        "videoUrl": "s3://test-bucket/test-video.mp4"
    }

    result = await process_segmentation_job(message)

    assert result["status"] == "success"
    assert result["totalEpisodes"] > 0
    assert all(ep["videoUrl"].startswith("s3://") for ep in result["episodes"])
```

**Load Testing:**
- Test with 3-hour, 5-hour, and 8-hour videos
- Verify memory doesn't exceed 8GB
- Ensure Gemini API rate limits are respected

---

### 8. Monitoring & Observability

**New Metrics to Track (New Relic):**

```python
# Custom metrics for segmentation

newrelic.agent.record_custom_metric("Custom/Segmentation/TotalEpisodes", total_episodes)
newrelic.agent.record_custom_metric("Custom/Segmentation/ProcessingTime", processing_time)
newrelic.agent.record_custom_metric("Custom/Segmentation/FailedEpisodes", failed_count)
newrelic.agent.record_custom_metric("Custom/Segmentation/GeminiAPILatency", gemini_latency)
newrelic.agent.record_custom_metric("Custom/Segmentation/S3UploadTime", upload_time)
```

**Logging:**
```python
logging.info(f"Starting segmentation for drama {drama_id}, {total_episodes} episodes")
logging.info(f"Segmented episode {episode_num}/{total_episodes} - {title}")
logging.info(f"Uploaded episode {episode_num} to S3: {video_key}")
logging.warning(f"Gemini API slow response for episode {episode_num}: {latency}s")
logging.error(f"Failed to upload episode {episode_num}: {error}")
```

**Alerts:**
- Segmentation job exceeds 2 hours
- More than 10% episode failures
- Gemini API quota near limit
- S3 upload failures exceed 5%

---

### 9. File Service Integration Requirements

**File Service Must:**

1. **Increase Upload Limit:**
   - Current: Assume ~500MB limit
   - New: 10GB+ for 3-hour videos
   - Update: Nginx/API Gateway upload limits

2. **Add New API Endpoint:**
   ```
   POST /api/dramas/segment
   {
     "videoId": "video-98765",
     "segmentDuration": 90
   }
   ```
   - Validates video exists
   - Publishes to `segmentation.video_uploaded` Kafka topic

3. **Database Schema Changes:**
   ```sql
   -- New table for micro dramas
   CREATE TABLE micro_dramas (
     id UUID PRIMARY KEY,
     title VARCHAR(255),
     original_video_id UUID REFERENCES videos(id),
     total_episodes INT,
     segmentation_status VARCHAR(50),
     created_at TIMESTAMP,
     updated_at TIMESTAMP
   );

   -- New table for episodes
   CREATE TABLE drama_episodes (
     id UUID PRIMARY KEY,
     drama_id UUID REFERENCES micro_dramas(id),
     episode_number INT,
     title VARCHAR(255),
     description TEXT,
     duration INT,
     video_url TEXT,
     s3_key VARCHAR(500),
     start_time INT,
     end_time INT,
     created_at TIMESTAMP
   );
   ```

4. **Preview Interface:**
   - Display all episodes with titles/descriptions
   - Allow creator to edit titles/descriptions before publishing
   - Support episode reordering (if needed)
   - Bulk publish to platform

5. **Kafka Consumer:**
   - Listen to `segmentation.segments_ready`
   - Process completed segmentation jobs
   - Update database with episode metadata

---

### 10. Migration Path & Rollout Plan

**Phase 1: Development (Week 1-2)**
- Implement segmentation module in existing service
- Add MoviePy integration
- Implement Gemini titling service
- Build S3 uploader
- Unit and integration tests

**Phase 2: Staging Deployment (Week 3)**
- Deploy to staging environment
- Test with sample 3-hour video
- Validate S3 structure
- Test Kafka integration with file-service staging

**Phase 3: Production Rollout (Week 4 - By Feb 19)**
- Deploy to production with feature flag (disabled)
- Increase S3 storage limits
- Update file-service with new endpoints
- Enable feature flag for beta creators
- Full launch on Feb 19, 2025

**Rollback Plan:**
- Feature flag can disable segmentation immediately
- Original video upload flow remains unchanged
- No database migrations required (additive only)

---

## Cost Analysis

**AWS S3 Storage (per 3-hour video):**
- Original video: ~5GB
- 120 episodes × ~42MB = ~5GB
- Total: ~10GB per drama
- Monthly cost (100 dramas): ~$23/month

**Gemini API Costs:**
- Frame-based analysis: ~120 requests × $0.001 = $0.12 per drama
- Video-based analysis: ~120 requests × $0.01 = $1.20 per drama
- **Recommended:** Frame-based ($0.12 per drama)

**Compute Costs:**
- Processing time: ~60 minutes per drama
- EC2 instance (t3.xlarge): $0.1664/hour
- Cost per drama: ~$0.17

**Total Cost per Drama:** ~$0.30 (+ S3 storage)

---

## Security Considerations

1. **S3 Access Control:**
   - Use IAM roles with least privilege
   - Presigned URLs expire after 7 days
   - Enable S3 bucket versioning

2. **Kafka Security:**
   - Use existing SCRAM authentication
   - Encrypt sensitive metadata in messages

3. **Video Content:**
   - Maintain content moderation for each segment
   - Apply same safety checks as original video

4. **Creator Permissions:**
   - Verify creator owns original video before segmentation
   - Audit log all segmentation requests

---

## Open Questions for CTO Review

1. **Service Placement:** Confirm preference for extending existing service vs. new service
2. **S3 Bucket:** Use existing bucket or create dedicated `circo-micro-dramas` bucket?
3. **Gemini Approach:** Frame-based or video-based analysis? (Recommend frame-based)
4. **Episode Editing:** Should creators be able to manually adjust episode boundaries?
5. **Retry Logic:** Automatic retry for failed episodes or manual trigger only?
6. **Preview Approval:** Must creators approve episodes before publishing, or auto-publish?
7. **Infrastructure:** Current service infrastructure (RAM, CPU) sufficient or need upgrade?

---

## Conclusion

Extending the existing `video_tagging_service` is the optimal approach for implementing micro drama segmentation by the February 19, 2025 deadline. The service already has the necessary infrastructure (Kafka, Gemini AI, S3, monitoring) and can be enhanced with MoviePy for precise video cutting.

**Key Success Factors:**
- Sequential 90-second segmentation with MoviePy
- Frame-based Gemini AI for cost-effective titling
- Organized S3 structure for scalable storage
- Robust error handling for production readiness
- Clear integration contract with file-service

**Timeline to Production:** 4 weeks (achievable for Feb 19 launch)

**Next Steps:**
1. CTO approval and decision on open questions
2. Kickoff development sprint
3. Coordinate with file-service team on integration
4. Deploy to staging for testing
5. Production rollout with feature flag

---

**Contact for Questions:**
Engineering Team Lead
