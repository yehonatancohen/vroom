"""
Query the Israeli government open-data vehicle registry (data.gov.il)
by license plate number and return enriched vehicle info.

API docs: https://data.gov.il/dataset/vehicle-data
Resource ID: 053cea08-09bc-40ec-8f7a-156f0677aff3
"""

import logging
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_API_URL = "https://data.gov.il/api/3/action/datastore_search"
_RESOURCE_ID = "053cea08-09bc-40ec-8f7a-156f0677aff3"

# Fields we care about, mapped to friendly names
_FIELD_MAP = {
    "mispar_rechev":    "plate",
    "tozeret_nm":       "manufacturer",
    "kinuy_mishari":    "model",
    "degem_nm":         "trim",
    "shnat_yitzur":     "year",
    "tzeva_rechev":     "color",
    "sug_delek_nm":     "fuel",
    "mivchan_acharon_dt": "last_test",
    "tokef_dt":         "test_valid_until",
    "mispar_baalim":    "owner_count",
    "moed_aliya_lakvish": "first_road_date",
    "baalut":           "ownership_type",
    "degem_manoa":      "engine_model",
    "nefah_manoa":      "engine_cc",
}


def lookup_plate(plate: str) -> Optional[dict]:
    """
    Look up a license plate in the gov.il vehicle registry.
    Returns a dict with normalized fields, or None on failure / not found.
    """
    plate = plate.strip().replace("-", "").replace(" ", "")
    if not plate:
        return None

    try:
        resp = requests.get(
            _API_URL,
            params={
                "resource_id": _RESOURCE_ID,
                "filters": f'{{"mispar_rechev": "{plate}"}}',
                "limit": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        logger.warning("gov.il plate lookup failed for %s: %s", plate, e)
        return None

    records = data.get("result", {}).get("records", [])
    if not records:
        logger.info("gov.il: no record found for plate %s", plate)
        return None

    raw = records[0]
    logger.debug("gov.il raw record for %s: %s", plate, raw)

    result = {}
    for api_key, friendly_key in _FIELD_MAP.items():
        val = raw.get(api_key)
        if val is not None and str(val).strip():
            result[friendly_key] = str(val).strip()

    return result or None
