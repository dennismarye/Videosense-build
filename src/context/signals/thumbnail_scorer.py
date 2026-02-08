"""
Thumbnail Scorer — advanced frame scoring using OpenCV.

V1 signal extractor that upgrades V0 thumbnail candidates with
computer-vision-based quality scoring: face detection, contrast analysis,
sharpness measurement, and rule-of-thirds composition checks.

Graceful fallback: if OpenCV is not installed, candidates pass through
unchanged with their V0 scores preserved.
"""

import logging
import os
from typing import Dict, List

from src.context.models import ThumbnailCandidate

logger = logging.getLogger(__name__)

# Try to import OpenCV — optional dependency
try:
    import cv2
    import numpy as np
    _CV2_AVAILABLE = True
except ImportError:
    _CV2_AVAILABLE = False
    logger.warning(
        "OpenCV (cv2) not installed — thumbnail_scorer will use V0 scores only. "
        "Install with: pip install opencv-python-headless"
    )

# ── Scoring weights ──────────────────────────────────────────

WEIGHT_FACE = 0.35
WEIGHT_CONTRAST = 0.25
WEIGHT_SHARPNESS = 0.25
WEIGHT_COMPOSITION = 0.15

# ── Thresholds ───────────────────────────────────────────────

# Laplacian variance below this is considered blurry
SHARPNESS_BLUR_THRESHOLD = 100.0
# Laplacian variance above this is considered sharp (used for normalization)
SHARPNESS_SHARP_CEILING = 800.0

# Histogram std dev below this is considered low contrast
CONTRAST_LOW_THRESHOLD = 40.0
# Histogram std dev above this is considered high contrast (for normalization)
CONTRAST_HIGH_CEILING = 80.0

# V1 vs V0 blending when rescoring
ADVANCED_WEIGHT = 0.6
ORIGINAL_WEIGHT = 0.4

# Maximum candidates to keep after rescoring
MAX_RESCORED_CANDIDATES = 5


def score_frame_advanced(frame_path: str) -> Dict:
    """
    Score a single frame using OpenCV-based quality metrics.

    Returns a dict with:
      - score: float (0.0-1.0, composite)
      - reasons: List[str]
      - face_score: float (0.0-1.0)
      - contrast_score: float (0.0-1.0)
      - sharpness_score: float (0.0-1.0)
      - composition_score: float (0.0-1.0)
    """
    if not _CV2_AVAILABLE:
        return {
            "score": 0.0,
            "reasons": ["opencv_unavailable"],
            "face_score": 0.0,
            "contrast_score": 0.0,
            "sharpness_score": 0.0,
            "composition_score": 0.0,
        }

    if not frame_path or not os.path.exists(frame_path):
        return {
            "score": 0.0,
            "reasons": ["frame_not_found"],
            "face_score": 0.0,
            "contrast_score": 0.0,
            "sharpness_score": 0.0,
            "composition_score": 0.0,
        }

    img = cv2.imread(frame_path)
    if img is None:
        return {
            "score": 0.0,
            "reasons": ["unreadable_frame"],
            "face_score": 0.0,
            "contrast_score": 0.0,
            "sharpness_score": 0.0,
            "composition_score": 0.0,
        }

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    reasons: List[str] = []

    # 1. Face detection (weight 0.35)
    face_score = _score_faces(gray, reasons)

    # 2. Contrast (weight 0.25)
    contrast_score = _score_contrast(gray, reasons)

    # 3. Sharpness (weight 0.25)
    sharpness_score = _score_sharpness(gray, reasons)

    # 4. Composition (weight 0.15)
    composition_score = _score_composition(gray, reasons)

    # Composite
    composite = (
        WEIGHT_FACE * face_score
        + WEIGHT_CONTRAST * contrast_score
        + WEIGHT_SHARPNESS * sharpness_score
        + WEIGHT_COMPOSITION * composition_score
    )
    composite = round(min(max(composite, 0.0), 1.0), 3)

    logger.info(
        f"Advanced score for {os.path.basename(frame_path)}: "
        f"{composite} (face={face_score:.2f}, contrast={contrast_score:.2f}, "
        f"sharpness={sharpness_score:.2f}, composition={composition_score:.2f})"
    )

    return {
        "score": composite,
        "reasons": reasons,
        "face_score": round(face_score, 3),
        "contrast_score": round(contrast_score, 3),
        "sharpness_score": round(sharpness_score, 3),
        "composition_score": round(composition_score, 3),
    }


def rescore_thumbnails(
    candidates: List[ThumbnailCandidate],
) -> List[ThumbnailCandidate]:
    """
    Re-score V0 thumbnail candidates with advanced OpenCV metrics.

    For each candidate with a frame_path, runs score_frame_advanced()
    and blends the new score with the original:
        final = 0.6 * advanced + 0.4 * original

    Returns candidates sorted by blended score descending, limited to top 5.
    """
    if not _CV2_AVAILABLE:
        logger.warning(
            "OpenCV not available — returning candidates with V0 scores unchanged"
        )
        return candidates

    if not candidates:
        return candidates

    rescored: List[ThumbnailCandidate] = []

    for candidate in candidates:
        if not candidate.frame_path:
            # No frame to analyze — keep original score
            rescored.append(candidate)
            continue

        result = score_frame_advanced(candidate.frame_path)

        if result["score"] == 0.0 and "opencv_unavailable" in result["reasons"]:
            # Shouldn't happen (checked above), but be safe
            rescored.append(candidate)
            continue

        # Blend V1 advanced score with V0 original
        original_score = candidate.score
        advanced_score = result["score"]
        blended = ADVANCED_WEIGHT * advanced_score + ORIGINAL_WEIGHT * original_score
        blended = round(min(max(blended, 0.0), 1.0), 3)

        # Merge reasons: keep original, add new
        merged_reasons = list(candidate.reasons)
        for reason in result["reasons"]:
            if reason not in merged_reasons:
                merged_reasons.append(reason)

        candidate.score = blended
        candidate.reasons = merged_reasons
        rescored.append(candidate)

    # Sort by blended score descending, keep top N
    rescored.sort(key=lambda c: c.score, reverse=True)
    rescored = rescored[:MAX_RESCORED_CANDIDATES]

    logger.info(
        f"Rescored {len(candidates)} candidates -> top {len(rescored)} "
        f"(best={rescored[0].score if rescored else 0})"
    )

    return rescored


# ── Internal scoring functions ───────────────────────────────


def _score_faces(gray: "np.ndarray", reasons: List[str]) -> float:
    """
    Detect faces using Haar cascade. Faces present = high score.

    Score logic:
      - 1+ faces detected: 1.0
      - 0 faces: 0.0
    """
    try:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)

        faces = face_cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=5,
            minSize=(30, 30),
        )

        count = len(faces) if faces is not None else 0

        if count > 0:
            reasons.append("face_detected")
            return 1.0
        return 0.0

    except Exception as e:
        logger.debug(f"Face detection failed: {e}")
        return 0.0


def _score_contrast(gray: "np.ndarray", reasons: List[str]) -> float:
    """
    Measure contrast via histogram standard deviation.

    A well-exposed image has pixel values spread across the full range,
    yielding a higher std dev. Flat/washed-out images cluster around
    a narrow band.
    """
    try:
        std_dev = float(np.std(gray))

        if std_dev >= CONTRAST_HIGH_CEILING:
            reasons.append("high_contrast")
            return 1.0
        elif std_dev <= CONTRAST_LOW_THRESHOLD:
            reasons.append("low_contrast")
            return round(std_dev / CONTRAST_LOW_THRESHOLD * 0.3, 3)
        else:
            # Linear interpolation between low and high thresholds
            score = (std_dev - CONTRAST_LOW_THRESHOLD) / (
                CONTRAST_HIGH_CEILING - CONTRAST_LOW_THRESHOLD
            )
            if score >= 0.7:
                reasons.append("high_contrast")
            else:
                reasons.append("low_contrast")
            return round(min(max(score, 0.0), 1.0), 3)

    except Exception as e:
        logger.debug(f"Contrast scoring failed: {e}")
        return 0.0


def _score_sharpness(gray: "np.ndarray", reasons: List[str]) -> float:
    """
    Measure sharpness via Laplacian variance.

    The Laplacian highlights edges; its variance indicates how many
    strong edges exist. Blurry frames have low variance.
    """
    try:
        laplacian = cv2.Laplacian(gray, cv2.CV_64F)
        variance = float(laplacian.var())

        if variance >= SHARPNESS_SHARP_CEILING:
            reasons.append("sharp_focus")
            return 1.0
        elif variance <= SHARPNESS_BLUR_THRESHOLD:
            reasons.append("blurry")
            return round(variance / SHARPNESS_BLUR_THRESHOLD * 0.3, 3)
        else:
            # Linear interpolation between blur and sharp thresholds
            score = (variance - SHARPNESS_BLUR_THRESHOLD) / (
                SHARPNESS_SHARP_CEILING - SHARPNESS_BLUR_THRESHOLD
            )
            if score >= 0.7:
                reasons.append("sharp_focus")
            else:
                reasons.append("blurry")
            return round(min(max(score, 0.0), 1.0), 3)

    except Exception as e:
        logger.debug(f"Sharpness scoring failed: {e}")
        return 0.0


def _score_composition(gray: "np.ndarray", reasons: List[str]) -> float:
    """
    Estimate composition quality using rule-of-thirds analysis.

    Divides the frame into a 3x3 grid and checks whether the cell
    with the highest brightness variance falls near a rule-of-thirds
    intersection point. High-interest content at these intersections
    is a hallmark of well-composed frames.

    Grid cell indices (row, col):
      (0,0) (0,1) (0,2)
      (1,0) (1,1) (1,2)
      (2,0) (2,1) (2,2)

    Rule-of-thirds intersection cells: (0,0), (0,2), (2,0), (2,2)
    Adjacent-to-intersection cells: (0,1), (1,0), (1,2), (2,1)
    """
    try:
        h, w = gray.shape[:2]
        cell_h = h // 3
        cell_w = w // 3

        # Compute variance for each cell in the 3x3 grid
        variances = {}
        for row in range(3):
            for col in range(3):
                y_start = row * cell_h
                y_end = (row + 1) * cell_h if row < 2 else h
                x_start = col * cell_w
                x_end = (col + 1) * cell_w if col < 2 else w

                cell = gray[y_start:y_end, x_start:x_end]
                variances[(row, col)] = float(np.var(cell))

        # Find the cell with the highest variance (most visual interest)
        max_cell = max(variances, key=variances.get)

        # Rule-of-thirds intersection cells (corners of inner grid)
        intersection_cells = {(0, 0), (0, 2), (2, 0), (2, 2)}
        # Cells adjacent to intersections (edges of grid)
        adjacent_cells = {(0, 1), (1, 0), (1, 2), (2, 1)}

        if max_cell in intersection_cells:
            reasons.append("good_composition")
            return 1.0
        elif max_cell in adjacent_cells:
            reasons.append("good_composition")
            return 0.7
        else:
            # Center cell (1,1) — acceptable but not ideal
            return 0.4

    except Exception as e:
        logger.debug(f"Composition scoring failed: {e}")
        return 0.0
