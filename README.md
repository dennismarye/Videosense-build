# Video Sense — Circo's AI Video Intelligence Engine

Video Sense is the intelligence layer behind Circo's creator platform. It analyzes
video content — audio, scenes, speech, motion, narrative — and produces actionable
outputs: teaser clips, platform-specific upload presets, content variants, thumbnail
crop recommendations, and monetization signals.

It is not a standalone product. It is a pipeline system designed to be embedded into
Circo Studio, Broadcast, Series, and Reach.

## Pipeline Versions

Video Sense uses an **additive pipeline architecture**. Each version extends the
previous one — no version branching, no feature flags, no conditional logic.

| Version | Steps  | What It Does |
|---------|--------|----------------------------------------------|
| **V0**  | 1-8    | Deterministic signal extraction: duration, scenes, silence, speech, thumbnails, topics, audio tone, summary |
| **V1**  | 9-15   | AI-enhanced analysis: narrative beats, hook scoring, quality assessment, clip ranking, safety check, platform bundles, EDL export |
| **V1.1**| 16-18  | Teaser engine: teaser selection, platform packaging, teaser export |
| **V1.2**| 19-22  | Content packaging: title/description generation, hashtag normalization, thumbnail crop recommendations, upload preset assembly |

Each version calls the previous: `V1.2 → V1.1 → V1 → V0`.

V1.1 and V1.2 steps are **fault-tolerant** — if any step fails, the pipeline logs
the error and continues. Prior version data is never lost.

## How to Run

### Install

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Run the Dev Server

```bash
uvicorn src.api.main:app --reload --port 8000
```

### Analyze a Video (CLI)

```bash
video-sense analyze /path/to/video.mp4 --pipeline v1.2 --output result.json
```

### Health Check

```
GET /health
```

### Docker

```bash
docker compose up --build
```

## Architecture Principles

1. **Additive pipelines** — V1.2 calls V1.1 which calls V1 which calls V0. No
   version branching. Every video always runs the full chain.

2. **No version branching** — There is no `if version == "v1.2"` anywhere. The
   pipeline is a linear chain of function calls.

3. **MockAI for deterministic testing** — All AI calls go through an `AIService`
   protocol. Tests use `MockAIService` which returns deterministic, non-random
   results. No external API calls in the test suite.

4. **Backward compatibility** — V1.2 models extend `VideoContext` with new optional
   fields. Existing V0/V1/V1.1 fields are never modified by V1.2 steps.

5. **Closure-based pipeline factories** — `create_v1_2_pipeline(ai_service)` returns
   an `async (VideoContext) -> VideoContext` function. The `JobManager` only knows
   about this signature — it doesn't know which pipeline version it's running.

6. **Fault tolerance** — V1.1 and V1.2 steps wrap each action in `try/except`. If
   step 20 (hashtags) fails, step 21 (crops) still runs. The pipeline only returns
   `FAILED` if the core V1 pipeline fails.

## Project Structure

```
src/
  actions/          Signal extractors and content generators
  api/              FastAPI + Strawberry GraphQL endpoints
  cli.py            Click CLI (video-sense command)
  config/           Settings and environment config
  context/          VideoContext model + ContextStore
  jobs/             Pipeline orchestration (V0, V1, V1.1, V1.2)
  local/            MockAIService for deterministic testing
  services/         AIService protocol definition
tests/              395 tests covering models, actions, pipelines, API
```

## Current Status

**Phase 4 of 6 complete.** The core engine is done — models, actions, pipeline
integration, and 395 passing tests. Remaining phases:

- Phase 5: API Layer (GraphQL types + `/dev/analyze-v1.2` endpoint)
- Phase 6: CLI Completion (finish `analyze` command for V1.2)
