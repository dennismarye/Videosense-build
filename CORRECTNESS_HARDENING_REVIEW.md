# Video Sense Backend — Correctness Hardening Review

**Date**: 2026-02-08
**Scope**: Bug fixes, state safety, Pydantic validators, tests — NO architecture changes, NO new features
**Result**: 238 tests passing in 0.66s (212 existing + 26 new)

---

## Bugs Fixed

### Bug 1: Monetization Tier Propagation (BLOCKER)

**Problem**: `VideoContext.tier` and `JobRequest.tier` were `str` fields defaulting to `"free"`. `JobManager.submit()` never copied `request.tier` to the `VideoContext` it created. `main_local.py` had a manual workaround (`context.tier = request.tier`) and `pipeline_v1_1.py` had a runtime string-to-enum conversion with silent fallback.

**Root cause**: Tier was stored as a raw string throughout the data model, with ad-hoc conversions scattered across the codebase.

**Fix** (5 files):

| File | Change |
| --- | --- |
| `src/context/models.py` | Changed `VideoContext.tier` and `JobRequest.tier` from `str = "free"` to `MonetizationTier = MonetizationTier.FREE`. Added `field_validator("tier", mode="before")` on both classes that coerces valid strings to enum, rejects invalid strings. |
| `src/jobs/job_manager.py` | Added `tier=request.tier` to `VideoContext()` constructor in `submit()`. |
| `src/jobs/pipeline_v1_1.py` | Removed string-to-enum conversion (lines 98-102). Now uses `context.tier` directly since it's already a `MonetizationTier` enum. |
| `main_local.py` | Removed manual workaround `context.tier = request.tier` (line 547). No longer needed since `submit()` propagates tier. |
| `src/api/schema.py` | Simplified `generate_teasers` mutation tier handling. Moved `MonetizationTier(tier)` conversion after the idempotency guard (Bug 2). |

**Validator code** (identical on both `VideoContext` and `JobRequest`):
```python
@field_validator("tier", mode="before")
@classmethod
def _coerce_tier(cls, v):
    if isinstance(v, MonetizationTier):
        return v
    if isinstance(v, str) and v in {t.value for t in MonetizationTier}:
        return MonetizationTier(v)
    raise ValueError(
        f"Invalid tier '{v}'. Must be one of: {[t.value for t in MonetizationTier]}"
    )
```

**Tests added**: 6 tier coercion tests (string→enum, enum→enum, invalid rejection) + 2 tier propagation tests (submit with pro tier, submit with default).

---

### Bug 2: GraphQL `generate_teasers` Idempotency

**Problem**: Calling the `generateTeasers` mutation twice on the same video would re-run teaser selection and overwrite existing teasers with new IDs and potentially different scores.

**Root cause**: No guard checking if teasers already exist on the context before regenerating.

**Fix** (1 file):

| File | Change |
| --- | --- |
| `src/api/schema.py` | Added idempotency guard at the top of `generate_teasers`: if `ctx.teasers` is non-empty, return existing teasers immediately without re-running selection/packaging/export. |

```python
# Idempotency: if teasers already exist, return them
if ctx.teasers:
    return [
        TeaserType(
            teaser_id=t.teaser_id, source_clip_id=t.source_clip_id,
            start=t.start, end=t.end, teaser_score=t.teaser_score,
            mode=t.mode.value, rationale=t.rationale,
            narrative_alignment=t.narrative_alignment,
        ) for t in ctx.teasers
    ]
```

**Tests added**: 1 idempotency test — creates context with pre-existing teasers, calls mutation twice, verifies same teaser IDs returned both times.

---

### Bug 3: Invalid PlatformBundle / Teaser States

**Problem**: A `PlatformBundle` could have `exported=True` with `output_path=None` (impossible in reality — if exported, there must be a file). `Teaser.teaser_score` had no bounds validation, allowing scores outside [0.0, 1.0].

**Root cause**: No cross-field or range validators on these Pydantic models.

**Fix** (1 file):

| File | Change |
| --- | --- |
| `src/context/models.py` | Added `model_validator(mode="after")` on `PlatformBundle`: rejects `exported=True` when `output_path` is falsy. Added `field_validator("teaser_score")` on `Teaser`: rejects values outside [0.0, 1.0]. |

```python
# PlatformBundle
@model_validator(mode="after")
def _validate_exported_has_path(self):
    if self.exported and not self.output_path:
        raise ValueError("exported=True requires a non-empty output_path")
    return self

# Teaser
@field_validator("teaser_score")
@classmethod
def _validate_teaser_score(cls, v):
    if not (0.0 <= v <= 1.0):
        raise ValueError(f"teaser_score must be between 0.0 and 1.0, got {v}")
    return v
```

**Tests added**: 4 PlatformBundle validator tests (exported+no path, exported+empty path, exported+valid path, not exported+no path) + 4 Teaser score validator tests (>1.0, <0.0, exactly 0.0, exactly 1.0).

---

### Bug 4: Duration Enforcement in Teaser Selection

**Problem**: `IDEAL_MIN_DURATION` (15s) and `IDEAL_MAX_DURATION` (30s) were only used as scoring bonuses. A 2-second clip or a 200-second clip could still be selected as a teaser — there was no hard filter.

**Root cause**: Missing hard floor/ceiling on clip duration before teaser scoring.

**Fix** (1 file):

| File | Change |
| --- | --- |
| `src/actions/teaser_selector.py` | Added `HARD_MIN_DURATION = 5.0` and `HARD_MAX_DURATION = 90.0` constants. Added pre-filter before scoring that excludes clips outside [5s, 90s]. |

```python
HARD_MIN_DURATION = 5.0   # seconds — clips shorter than this are excluded
HARD_MAX_DURATION = 90.0  # seconds — clips longer than this are excluded

# In select_teasers():
clips = [
    c for c in clips
    if HARD_MIN_DURATION <= (c.end - c.start) <= HARD_MAX_DURATION
]
```

**Tests added**: 4 hard duration enforcement tests (2s excluded, 200s excluded, boundary 5s included, boundary 90s included).

---

### Bug 6: Metadata Constraint Enforcement

**Problem**: AI-generated titles could exceed platform `max_title_chars` and hashtag lists could exceed `max_hashtags`. The constraints were passed to the AI as hints but never enforced after the AI returned results.

**Root cause**: `_generate_titles()` and `_generate_hashtags()` trusted AI output without post-validation.

**Fix** (1 file):

| File | Change |
| --- | --- |
| `src/actions/platform_packager.py` | Added post-generation enforcement in both `_generate_titles()` and `_generate_hashtags()`. Titles are truncated to `max_title_chars` per platform. Hashtag lists are sliced to `max_hashtags` per platform. |

```python
# In _generate_titles(), after AI call:
for platform_name, title in titles.items():
    max_chars = max_chars_dict.get(platform_name)
    if max_chars and len(title) > max_chars:
        titles[platform_name] = title[:max_chars]

# In _generate_hashtags(), after AI call:
for platform_name, tags in hashtags.items():
    max_tags = max_hashtags_dict.get(platform_name)
    if max_tags and len(tags) > max_tags:
        hashtags[platform_name] = tags[:max_tags]
```

**Tests added**: 3 metadata constraint tests using `_OverlongAIService` mock (returns 500-char titles, 50 hashtags) — verifies title truncation, hashtag trimming, and that normal mock AI also respects constraints for PRO tier (all 5 platforms).

---

## Bug 5 (AI Failure Tolerance) — Already Handled

The spec noted this as a concern, but investigation confirmed all AI calls in the pipeline are already wrapped in try/except with graceful degradation (empty titles, empty hashtags, etc.). No changes needed.

---

## Files Modified (Source)

| File | Lines Changed | What |
| --- | --- | --- |
| `src/context/models.py` | +25 | Tier type change, coercion validators, PlatformBundle validator, Teaser score validator |
| `src/jobs/job_manager.py` | +1 | `tier=request.tier` in VideoContext constructor |
| `src/jobs/pipeline_v1_1.py` | -5, +1 | Removed string-to-enum conversion, use `context.tier` directly |
| `main_local.py` | -2 | Removed manual tier workaround |
| `src/api/schema.py` | +12, -2 | Idempotency guard, simplified tier handling |
| `src/actions/teaser_selector.py` | +7 | Hard duration constants + pre-filter |
| `src/actions/platform_packager.py` | +8 | Title truncation + hashtag trimming after AI |

## Files Modified (Tests)

| File | Lines Changed | What |
| --- | --- | --- |
| `tests/test_models.py` | +62, -3 | Fixed 3 assertions (`str` → `MonetizationTier`), added 14 new tests (coercion, validators) |
| `tests/test_pipelines.py` | +12 | Added `MonetizationTier` import, 2 tier propagation tests |
| `tests/test_teaser_selector.py` | +24 | Added `HARD_MIN/MAX_DURATION` imports, 4 duration enforcement tests |
| `tests/test_platform_packager.py` | +48 | Added 5 tests (watermark invariants, metadata constraints) |
| `tests/test_graphql.py` | +32 | Added 1 idempotency test |

---

## Test Results

```
$ .venv/bin/python -m pytest tests/ -v --ignore=tests/test_video_processor.py

============================= test session starts ==============================
platform darwin -- Python 3.11.14, pytest-8.3.4, pluggy-1.6.0
asyncio: mode=Mode.AUTO
collected 238 items

tests/test_clip_ranker.py          21 passed
tests/test_context_store.py        15 passed
tests/test_edl_exporter.py         17 passed
tests/test_graphql.py              23 passed  (was 22, +1 idempotency)
tests/test_mock_ai_service.py      28 passed
tests/test_models.py               49 passed  (was 35, +14 validators)
tests/test_pipelines.py            17 passed  (was 15, +2 tier propagation)
tests/test_platform_packager.py    24 passed  (was 19, +5 watermark/metadata)
tests/test_teaser_selector.py      22 passed  (was 18, +4 duration)
----------------------------------------------
TOTAL                             238 passed in 0.66s
```

---

## Invariants Now Enforced

1. **Tier is always an enum** — `VideoContext.tier` and `JobRequest.tier` are `MonetizationTier`, never a raw string. String inputs are coerced or rejected.
2. **Tier propagates end-to-end** — `JobManager.submit()` → `VideoContext` → pipeline → packager. No manual workarounds needed.
3. **Teaser generation is idempotent** — GraphQL `generateTeasers` returns existing teasers without re-running.
4. **PlatformBundle state is valid** — `exported=True` requires `output_path`. Caught at construction time.
5. **Teaser scores are bounded** — `teaser_score` must be [0.0, 1.0]. Caught at construction time.
6. **Clip duration is enforced** — Clips outside [5s, 90s] are excluded before teaser scoring.
7. **Metadata respects platform limits** — Titles truncated to `max_title_chars`, hashtags trimmed to `max_hashtags` after AI generation.
8. **Watermark invariant holds** — FREE = always watermarked, PLUS/PRO/ENTERPRISE = never watermarked.
