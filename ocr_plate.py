"""
License plate OCR via Plate Recognizer API (platerecognizer.com).
Free tier: 2500 calls/month.

Set PLATE_RECOGNIZER_TOKEN in .env to enable.
"""

import logging
from typing import Optional

import requests

from config import PLATE_RECOGNIZER_TOKEN

logger = logging.getLogger(__name__)

_API_URL = "https://api.platerecognizer.com/v1/plate-reader/"


def ocr_plate_from_url(image_url: str) -> Optional[str]:
    """
    Send an image URL to Plate Recognizer and return the best plate candidate,
    or None if not found / token not configured.
    """
    if not PLATE_RECOGNIZER_TOKEN:
        return None

    try:
        resp = requests.post(
            _API_URL,
            headers={"Authorization": f"Token {PLATE_RECOGNIZER_TOKEN}"},
            data={"regions": ["il"]},   # hint: Israeli plates
            json={"url": image_url},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("Plate Recognizer API error for %s: %s", image_url, e)
        return None

    results = data.get("results", [])
    if not results:
        logger.debug("Plate Recognizer: no plate found in %s", image_url)
        return None

    # Pick the result with the highest confidence
    best = max(results, key=lambda r: r.get("score", 0))
    plate = best.get("plate", "").strip().upper()
    score = best.get("score", 0)
    logger.info("Plate Recognizer: found '%s' (score=%.2f) in %s", plate, score, image_url)
    return plate or None
