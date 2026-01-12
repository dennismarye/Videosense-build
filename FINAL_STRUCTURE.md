# Video Fragmentation - Final Structure

## ✅ Updated Implementation

### S3 Structure (Using Existing Buckets)

```
Development:
s3://app.circleandclique.org/original-files/
  ├── {jobId-1}/
  │   ├── episode-0001.mp4
  │   ├── episode-0002.mp4
  │   └── episode-0015.mp4
  ├── {jobId-2}/
  │   ├── episode-0001.mp4
  │   ├── episode-0002.mp4
  │   └── episode-0020.mp4
  └── ...

Staging:
s3://app.circleandclique.org/original-files/{jobId}/episode-{number}.mp4

Production:
s3://prod.circleandclique.org/original-files/{jobId}/episode-{number}.mp4
```

---

## Environment Configuration

**AUTOMATIC BUCKET SELECTION** - No manual configuration needed!

The `FRAGMENTATION_OUTPUT_BUCKET` is automatically selected based on `NODE_ENV` via property decorator in [settings.py:106-116](src/config/settings.py#L106-L116):

```python
@property
def FRAGMENTATION_OUTPUT_BUCKET(self) -> str:
    if self.NODE_ENV.lower() == "production":
        return "prod.circleandclique.org"
    else:
        return "app.circleandclique.org"
```

### Development (.env)
```bash
NODE_ENV=development
ENABLE_VIDEO_FRAGMENTATION=true
FRAGMENT_SAFETY_THRESHOLD=85
FRAGMENT_ALLOWED_DURATIONS=[90, 180, 360]
FRAGMENT_DEFAULT_DURATION=180
FRAGMENTATION_TEMP_DIR=/tmp/video_fragmentation
FRAGMENT_OUTPUT_TOPIC=fragmentation.fragments_ready
# FRAGMENTATION_OUTPUT_BUCKET → Automatic: app.circleandclique.org
```

### QA (.env)
```bash
NODE_ENV=qa
ENABLE_VIDEO_FRAGMENTATION=true
# ... same settings as development
# FRAGMENTATION_OUTPUT_BUCKET → Automatic: app.circleandclique.org
```

### Staging (.env)
```bash
NODE_ENV=staging
ENABLE_VIDEO_FRAGMENTATION=true
# ... same settings as development
# FRAGMENTATION_OUTPUT_BUCKET → Automatic: app.circleandclique.org
```

### Production (.env)
```bash
NODE_ENV=production
ENABLE_VIDEO_FRAGMENTATION=true
FRAGMENT_SAFETY_THRESHOLD=85
FRAGMENT_ALLOWED_DURATIONS=[90, 180, 360]
FRAGMENT_DEFAULT_DURATION=180
FRAGMENTATION_TEMP_DIR=/tmp/video_fragmentation
FRAGMENT_OUTPUT_TOPIC=fragmentation.fragments_ready
# FRAGMENTATION_OUTPUT_BUCKET → Automatic: prod.circleandclique.org
```

---

## Kafka Message Structure (from file-service)

```json
{
  "jobId": "job-12345",
  "files": [
    {
      "fileType": "Video",
      "original": "s3://app.circleandclique.org/original-files/video.mp4"
    }
  ],
  "fragment": true,
  "fragmentConfig": {
    "requestedSegmentDuration": 180
  },
  "format": "video",
  "primaryCaption": "Check out my new drama series!",
  "title": "My Drama Series",
  "description": "An amazing story"
}
```

**Key Points:**
- ✅ **No `videoId`** - Only `jobId` (it's unique)
- ✅ **No `creatorId`** - Not needed for fragmentation
- ✅ `fragment: true` triggers fragmentation
- ✅ `requestedSegmentDuration`: 90, 180, or 360 seconds
- ✅ **Description fields (ALL OPTIONAL)**: `title`, `secondaryCaption`, `primaryCaption`, `description`
  - Service combines whichever exist for description analysis
  - Priority: title → secondaryCaption → primaryCaption → description
  - Implemented in both fragmentation AND classification workflows

---

## Kafka Response (to file-service)

**Topic:** `fragmentation.fragments_ready`

```json
{
  "jobId": "job-12345",
  "status": "success",
  "fragmentationComplete": true,
  "totalEpisodes": 15,
  "segmentDuration": 180,
  "episodes": [
    {
      "episodeNumber": 1,
      "startTime": 0,
      "endTime": 180,
      "duration": 180,
      "filename": "episode_0001.mp4",
      "fileSize": 15728640,
      "success": true,
      "s3Key": "original-files/job-12345/episode-0001.mp4",
      "s3Url": "s3://app.circleandclique.org/original-files/job-12345/episode-0001.mp4",
      "presignedUrl": "https://app.circleandclique.org.s3.amazonaws.com/original-files/job-12345/episode-0001.mp4?...",
      "bucket": "app.circleandclique.org"
    },
    {
      "episodeNumber": 2,
      "startTime": 180,
      "endTime": 360,
      "duration": 180,
      "filename": "episode_0002.mp4",
      "fileSize": 15932416,
      "success": true,
      "s3Key": "original-files/job-12345/episode-0002.mp4",
      "s3Url": "s3://app.circleandclique.org/original-files/job-12345/episode-0002.mp4",
      "presignedUrl": "https://app.circleandclique.org.s3.amazonaws.com/original-files/job-12345/episode-0002.mp4?...",
      "bucket": "app.circleandclique.org"
    }
    // ... remaining 13 episodes
  ],
  "processingTime": 1200,
  "timestamp": 1704729600
}
```

---

## Easy Querying

### AWS CLI

**List all episodes for a job:**
```bash
aws s3 ls s3://app.circleandclique.org/original-files/job-12345/
```

**Download all episodes for a job:**
```bash
aws s3 sync s3://app.circleandclique.org/original-files/job-12345/ ./job-12345-episodes/
```

**Count episodes:**
```bash
aws s3 ls s3://app.circleandclique.org/original-files/job-12345/ | wc -l
```

**Get specific episode:**
```bash
aws s3 cp s3://app.circleandclique.org/original-files/job-12345/episode-0001.mp4 ./
```

### Boto3

```python
import boto3

s3 = boto3.client('s3')

# List all episodes for a job
response = s3.list_objects_v2(
    Bucket='app.circleandclique.org',
    Prefix='original-files/job-12345/'
)

episodes = [obj['Key'] for obj in response.get('Contents', [])]
print(episodes)
# ['original-files/job-12345/episode-0001.mp4',
#  'original-files/job-12345/episode-0002.mp4', ...]
```

### SQL Query (if using database)

```sql
SELECT * FROM video_episodes
WHERE job_id = 'job-12345'
ORDER BY episode_number;
```

---

## Database Schema (Recommended)

```sql
CREATE TABLE video_episodes (
    id UUID PRIMARY KEY,
    job_id VARCHAR(255) NOT NULL,
    episode_number INT NOT NULL,
    start_time INT NOT NULL,
    end_time INT NOT NULL,
    duration INT NOT NULL,
    s3_key VARCHAR(500) NOT NULL,
    s3_url TEXT NOT NULL,
    presigned_url TEXT,
    file_size BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_job_id (job_id),
    INDEX idx_s3_key (s3_key),
    UNIQUE INDEX idx_job_episode (job_id, episode_number)
);
```

**Queries:**

```sql
-- Get all episodes for a job
SELECT * FROM video_episodes
WHERE job_id = 'job-12345'
ORDER BY episode_number;

-- Get specific episode
SELECT * FROM video_episodes
WHERE job_id = 'job-12345' AND episode_number = 1;

-- Count episodes for a job
SELECT COUNT(*) FROM video_episodes
WHERE job_id = 'job-12345';
```

---

## Key Benefits

✅ **Job-Based Organization** - Each job gets its own folder with all episodes
✅ **No VideoId Needed** - JobId is sufficient and unique
✅ **Existing Buckets** - Reuses current S3 infrastructure
✅ **Easy Querying** - Simple prefix-based queries per job
✅ **Clean Isolation** - Episodes grouped by job, not scattered
✅ **Clear Naming** - `episode-0001.mp4` instead of `fragment-0001.mp4`

---

## Example Flow

1. **User uploads 3-hour video** → File-service sends message with `fragment: true`
2. **Video tagging service:**
   - Runs safety check
   - If safe → Segments into 60 episodes (180s each)
   - Uploads to `s3://app.circleandclique.org/original-files/job-12345/episode-000X.mp4`
3. **File-service receives Kafka message** with all 60 episodes metadata
4. **File-service stores in database** and shows preview to creator
5. **Creator views all 60 episodes** grouped by jobId

---

---

## 🚀 Deployment Checklist

### Pre-Deployment
- [ ] **Dependencies Installed**: `pip install -r requirements.txt`
  - MoviePy, imageio, imageio-ffmpeg added
- [ ] **FFmpeg Available**: Verify `ffmpeg -version` works
- [ ] **S3 Buckets Accessible**: Test write permissions to `original-files/{jobId}/` folders
- [ ] **Kafka Topic Created**: `fragmentation.fragments_ready` topic exists
- [ ] **Temp Directory Writable**: `/tmp/video_fragmentation` has sufficient space
- [ ] **Environment Variables Set**: See configurations above

### Testing
- [ ] **Test Safety-First Logic**: Fragment flag ignored if safety fails
- [ ] **Test 90s Segmentation**: Verify episode creation with 90-second segments
- [ ] **Test 180s Segmentation**: Verify episode creation with 180-second segments
- [ ] **Test 360s Segmentation**: Verify episode creation with 360-second segments
- [ ] **Test S3 Upload**: Verify job-based folder structure
- [ ] **Test Presigned URLs**: Verify 7-day expiry
- [ ] **Test Cleanup**: Verify temp files removed after processing
- [ ] **Test Environment Buckets**: Verify production → prod bucket, dev → app bucket

### Monitoring
- [ ] **New Relic Metrics**: Check `fragmentation.success` and `fragmentation.total_fragments`
- [ ] **Log Monitoring**: Search for "Starting fragmentation" and "Fragmentation complete"
- [ ] **S3 Storage**: Monitor storage growth in buckets
- [ ] **Processing Time**: Track average time per video length

### File-Service Integration
- [ ] **Kafka Message Format**: Ensure `fragment: true` and `fragmentConfig` included
- [ ] **Consumer Setup**: File-service subscribed to `fragmentation.fragments_ready`
- [ ] **Database Schema**: Episodes table created with job_id foreign key
- [ ] **UI Display**: Creator can view all episodes grouped by jobId

---

## 🎯 Workflow Logic

### Safety-First Fragmentation (main.py:141-175)
```
1. Receive Kafka message with fragment=true
   ↓
2. Run safety check (existing workflow)
   ↓
3. Calculate safety score from contentFlag:
   - SAFE = 100
   - RESTRICT_18+ = 85
   - Other = 0
   ↓
4. Check fragmentation conditions:
   - ENABLE_VIDEO_FRAGMENTATION = true
   - message.fragment = true
   - safety_score ≥ FRAGMENT_SAFETY_THRESHOLD (85)
   - contentFlag in ["SAFE", "RESTRICT_18+"]
   ↓
5. If ALL true → process_fragmentation()
   ↓
6. Produce to fragmentation.fragments_ready
   ↓
7. Continue to quality analysis (existing)
```

### Fragmentation Process (fragment_processor.py:81-178)
```
1. Extract video URL from message.files[0].original
   ↓
2. Validate segment duration (must be 90, 180, or 360)
   ↓
3. Download video from S3 → /tmp/video_fragmentation/{jobId}_source.mp4
   ↓
4. Segment using MoviePy:
   - Cut at fixed time intervals
   - Save as episode-XXXX.mp4
   ↓
5. Upload each episode:
   - Path: original-files/{jobId}/episode-{number}.mp4
   - S3 metadata: job-id, episode-number, start-time, etc.
   - Generate 7-day presigned URL
   ↓
6. Cleanup: Remove source video and temp segments
   ↓
7. Return result with all episode metadata
```

---

## 🐛 Debugging

### Common Errors

**"Invalid segment duration"**
- **Cause**: requestedSegmentDuration not in [90, 180, 360]
- **Fix**: Update fragmentConfig.requestedSegmentDuration

**"Safety score below threshold"**
- **Cause**: Video failed safety check (score < 85)
- **Fix**: Content needs review - fragmentation skipped by design

**"No video URL found"**
- **Cause**: Missing files[0].original or videoDetails.originalVideoUrl
- **Fix**: Ensure Kafka message includes video URL

**"Video download failed"**
- **Cause**: S3 permissions or invalid URL
- **Fix**: Verify AWS credentials and S3 bucket access

**"Segmentation failed"**
- **Cause**: FFmpeg not installed or temp directory not writable
- **Fix**: Install FFmpeg and check /tmp/video_fragmentation permissions

### Log Locations
```bash
# Fragmentation started
grep "Starting fragmentation for job" app.log

# Episodes created
grep "Created.*fragments" app.log

# Upload status
grep "Uploaded.*episodes successfully" app.log

# Errors
grep "Error in fragmentation workflow" app.log
```

---

## 🔧 Quick Actions

### Disable Fragmentation (Emergency)
```bash
# Set environment variable
export ENABLE_VIDEO_FRAGMENTATION=false

# Restart service
systemctl restart video-tagging-service
```

### Change Safety Threshold
```python
# In src/config/settings.py
FRAGMENT_SAFETY_THRESHOLD: int = 90  # More strict (default: 85)
```

### Add New Duration
```python
# In src/config/settings.py
FRAGMENT_ALLOWED_DURATIONS: list = [90, 180, 360, 600]  # Added 10 minutes
```

---

## 📊 Key Files Modified

| File | Changes | Purpose |
|------|---------|---------|
| `main.py:141-175` | Added fragmentation check after safety | Orchestration |
| `src/video_fragmentation/fragment_processor.py` | New | Main workflow |
| `src/video_fragmentation/video_segmenter.py` | New | MoviePy cutting |
| `src/video_fragmentation/s3_fragment_uploader.py` | New | S3 upload |
| `src/config/settings.py:106-116` | Added property decorator | Auto bucket selection |
| `src/video_processor/video_processor.py` | Updated description extraction | Unified logic |
| `requirements.txt` | Added MoviePy, imageio | Dependencies |

---

## ✅ Implementation Complete

All features for **Stage 1 (Basic Fragmentation)** are complete and ready for deployment:

- ✅ Safety-first workflow
- ✅ Job-based S3 structure
- ✅ Automatic environment bucket selection
- ✅ Episode naming (not fragment)
- ✅ Only jobId used (no videoId needed)
- ✅ Unified description field handling
- ✅ MoviePy video segmentation
- ✅ 7-day presigned URLs
- ✅ Temp file cleanup
- ✅ New Relic monitoring
- ✅ Kafka integration

**Stage 2 (Future - Gemini AI Episode Titling)** is documented but not yet scheduled for implementation.

---

## Environment Setup

**No new buckets needed!** Uses your existing S3 infrastructure with automatic bucket selection based on NODE_ENV.
