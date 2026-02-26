"""
tools/location_tool.py
Geocode a text address/landmark using Amazon Location Service.

For the prototype, if the location can't be resolved we return a Bengaluru
city-centre coordinate as a safe fallback so the rest of the pipeline still runs.

Real integration: create an Amazon Location Place Index (e.g. "abdm-place-index")
in your AWS account and set LOCATION_PLACE_INDEX in .env.
"""

import logging
import os
import boto3
from botocore.exceptions import ClientError

from config import settings

log = logging.getLogger(__name__)

PLACE_INDEX = os.getenv("LOCATION_PLACE_INDEX", "abdm-place-index")
FALLBACK_LAT = 12.9716
FALLBACK_LON = 77.5946   # Bengaluru city centre

_client = boto3.client(
    "location",
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
)


def geocode(address: str) -> tuple[float, float]:
    """
    Attempt to geocode `address` using Amazon Location.
    Returns (latitude, longitude).
    Falls back to Bengaluru centre if the index doesn't exist or lookup fails.
    """
    try:
        resp = _client.search_place_index_for_text(
            IndexName=PLACE_INDEX,
            Text=address,
            MaxResults=1,
            FilterCountries=["IND"],
        )
        results = resp.get("Results", [])
        if results:
            point = results[0]["Place"]["Geometry"]["Point"]
            lon, lat = point[0], point[1]
            log.info("[Location] Geocoded '%s' → (%.4f, %.4f)", address, lat, lon)
            return lat, lon
    except ClientError as exc:
        code = exc.response["Error"]["Code"]
        if code == "ResourceNotFoundException":
            log.warning(
                "[Location] Place index '%s' not found — using fallback coords. "
                "Create it in the AWS console or set LOCATION_PLACE_INDEX.",
                PLACE_INDEX,
            )
        else:
            log.warning("[Location] Geocode failed (%s) — using fallback coords.", code)
    except Exception as exc:
        log.warning("[Location] Unexpected error: %s — using fallback coords.", exc)

    log.info("[Location] Fallback coords: (%.4f, %.4f)", FALLBACK_LAT, FALLBACK_LON)
    return FALLBACK_LAT, FALLBACK_LON
