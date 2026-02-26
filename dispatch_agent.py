"""
agents/dispatch_agent.py
DISPATCH AGENT
==============
Finds the nearest available ambulance from a dummy fleet,
"dispatches" it, starts a simulated GPS location stream,
and returns a tracking URL.

PLACEHOLDER LOGIC:
  - Fleet is read from config (3 dummy units in Bengaluru)
  - Distance calculated with Haversine formula
  - ETA = distance / 40 km/h (urban average)
  - Tracking URL is a local stub — replace with IoT Core / real GPS feed later
  - GPS stream is simulated in a background thread (logs position every 5 s)

REAL INTEGRATION POINTS (marked with # [REPLACE]):
  - find_nearest_ambulance → query your fleet management DB / Amazon Location
  - send_dispatch_command  → AWS IoT Core MQTT publish to ambulance MDT
  - GPS stream             → IoT Core + Kinesis Data Streams
  - Tracking URL           → API Gateway WebSocket endpoint backed by IoT Core
"""

import asyncio
import logging
import math
import threading
import time
from config import settings
from models import AmbulanceUnit, DispatchResult

log = logging.getLogger(__name__)


# ── Haversine distance ─────────────────────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Dummy fleet loader ─────────────────────────────────────────────────────────

def _load_fleet() -> list[AmbulanceUnit]:
    units = []
    for entry in settings.dummy_ambulance_fleet.split(","):
        parts = entry.strip().split(":")
        if len(parts) == 3:
            lat, lon, uid = float(parts[0]), float(parts[1]), parts[2]
            units.append(AmbulanceUnit(unit_id=uid, latitude=lat, longitude=lon))
    return units


# ── Simulated GPS stream ───────────────────────────────────────────────────────

def _simulate_gps_stream(unit: AmbulanceUnit, dest_lat: float, dest_lon: float):
    """
    Background thread: logs simulated GPS movement toward the destination.
    [REPLACE] In production: subscribe to IoT Core MQTT topic and push to Kinesis.
    """
    steps = 10
    cur_lat, cur_lon = unit.latitude, unit.longitude
    d_lat = (dest_lat - cur_lat) / steps
    d_lon = (dest_lon - cur_lon) / steps

    log.info("[Dispatch][GPS-SIM] Starting GPS stream for %s", unit.unit_id)
    for i in range(steps):
        time.sleep(5)
        cur_lat += d_lat
        cur_lon += d_lon
        remaining_km = _haversine_km(cur_lat, cur_lon, dest_lat, dest_lon)
        log.info(
            "[Dispatch][GPS-SIM] %s → (%.4f, %.4f) | %.2f km to scene",
            unit.unit_id, cur_lat, cur_lon, remaining_km,
        )
    log.info("[Dispatch][GPS-SIM] %s reached scene.", unit.unit_id)


# ── Tools ──────────────────────────────────────────────────────────────────────

def find_nearest_ambulance(lat: float, lon: float) -> AmbulanceUnit:
    """
    [PLACEHOLDER] Return the closest unit from the dummy fleet.
    [REPLACE] Query fleet management system / Amazon Location tracker.
    """
    fleet = _load_fleet()
    for unit in fleet:
        unit.eta_minutes = (_haversine_km(lat, lon, unit.latitude, unit.longitude) / 40) * 60

    nearest = min(fleet, key=lambda u: u.eta_minutes)
    log.info(
        "[Dispatch] Nearest unit: %s | ETA ~%.1f min",
        nearest.unit_id, nearest.eta_minutes,
    )
    return nearest


def send_dispatch_command(unit: AmbulanceUnit, dest_lat: float, dest_lon: float) -> bool:
    """
    [PLACEHOLDER] Simulate sending a dispatch command to the ambulance MDT.
    [REPLACE] boto3 IoT Core: publish to topic 'ambulance/{unit_id}/dispatch'
    """
    log.info(
        "[Dispatch] Dispatch command sent to %s → (%.4f, %.4f)",
        unit.unit_id, dest_lat, dest_lon,
    )
    print(f"\n[DISPATCH] 🚑 Unit {unit.unit_id} dispatched! ETA ~{unit.eta_minutes:.0f} min")
    return True


def publish_tracking_url(session_id: str, unit_id: str) -> str:
    """
    [PLACEHOLDER] Return a stub tracking URL.
    [REPLACE] Create a signed API Gateway WebSocket URL that reads IoT Core position feed.
    """
    url = f"http://localhost:8000/track/{session_id}/{unit_id}"
    log.info("[Dispatch] Tracking URL: %s", url)
    return url


# ── Main agent entry ───────────────────────────────────────────────────────────

async def run(session_id: str, lat: float, lon: float) -> DispatchResult:
    """
    Full dispatch flow.
    Called as soon as location is confirmed — runs in parallel with intake.
    """
    log.info("[Dispatch] Agent starting for session %s | target=(%.4f, %.4f)", session_id, lat, lon)

    # Run blocking work in thread pool
    loop = asyncio.get_event_loop()
    unit: AmbulanceUnit = await loop.run_in_executor(
        None, find_nearest_ambulance, lat, lon
    )
    await loop.run_in_executor(None, send_dispatch_command, unit, lat, lon)

    tracking_url = publish_tracking_url(session_id, unit.unit_id)

    # Start simulated GPS stream in background (daemon thread — won't block shutdown)
    gps_thread = threading.Thread(
        target=_simulate_gps_stream,
        args=(unit, lat, lon),
        daemon=True,
    )
    gps_thread.start()

    result = DispatchResult(unit=unit, tracking_url=tracking_url)
    log.info("[Dispatch] Complete. unit=%s tracking=%s", unit.unit_id, tracking_url)
    return result
