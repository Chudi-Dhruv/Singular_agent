"""
agents/hospital_router.py
HOSPITAL ROUTER AGENT
=====================
Selects the best hospital for the patient based on:
  - Care type (specialty required)
  - Distance from scene
  - Available beds
  - Insurance match

PLACEHOLDER LOGIC:
  - Hospital "database" is a hardcoded list of 6 hospitals in Bengaluru
  - Scoring formula: 0.4×distance_score + 0.3×bed_score + 0.2×specialty_score + 0.1×insurance_score
  - Prenotification is a log print (replace with SNS/API call)
  - QR generation is real (uses tools/qr_tool.py)

REAL INTEGRATION POINTS (marked with # [REPLACE]):
  - Hospital DB     → Amazon RDS (PostgreSQL) with ABDM FHIR hospital registry
  - Bed capacity    → ABDM Health Facility Registry API
  - Insurance check → Insurer API / lookup table in RDS
  - Prenotification → Amazon SNS topic / direct hospital API
"""

import asyncio
import logging
import math
from models import IncidentData, SeverityResult, Hospital, RoutingResult, CareType
from tools.qr_tool import generate_qr

log = logging.getLogger(__name__)


# ── Placeholder hospital database ─────────────────────────────────────────────
# [REPLACE] with RDS query / ABDM API call

HOSPITAL_DB: list[dict] = [
    {
        "hospital_id": "H001",
        "name": "Manipal Hospital (Old Airport Road)",
        "latitude": 12.9592, "longitude": 77.6460,
        "specialties": ["cardiac", "trauma", "neuro", "ortho", "general"],
        "available_beds": 12,
        "accepts_insurance": ["STAR", "NIVA", "HDFC", "ICICI", "GOVT"],
    },
    {
        "hospital_id": "H002",
        "name": "Fortis Hospital (Bannerghatta Road)",
        "latitude": 12.8914, "longitude": 77.5971,
        "specialties": ["cardiac", "ortho", "general"],
        "available_beds": 6,
        "accepts_insurance": ["STAR", "HDFC", "ICICI"],
    },
    {
        "hospital_id": "H003",
        "name": "NIMHANS (Neuro specialist)",
        "latitude": 12.9408, "longitude": 77.5964,
        "specialties": ["neuro", "general"],
        "available_beds": 4,
        "accepts_insurance": ["GOVT", "ESI"],
    },
    {
        "hospital_id": "H004",
        "name": "Victoria Hospital (Trauma Centre)",
        "latitude": 12.9659, "longitude": 77.5717,
        "specialties": ["trauma", "ortho", "general"],
        "available_beds": 20,
        "accepts_insurance": ["GOVT", "ESI", "NIVA"],
    },
    {
        "hospital_id": "H005",
        "name": "Apollo Hospital (Jayanagar)",
        "latitude": 12.9299, "longitude": 77.5884,
        "specialties": ["cardiac", "neuro", "trauma", "ortho", "general"],
        "available_beds": 8,
        "accepts_insurance": ["STAR", "NIVA", "HDFC", "ICICI", "GOVT"],
    },
    {
        "hospital_id": "H006",
        "name": "Sakra World Hospital",
        "latitude": 12.9785, "longitude": 77.6948,
        "specialties": ["trauma", "ortho", "general"],
        "available_beds": 3,
        "accepts_insurance": ["HDFC", "ICICI"],
    },
]


# ── Utilities ─────────────────────────────────────────────────────────────────

def _haversine_km(lat1, lon1, lat2, lon2) -> float:
    R = 6371.0
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1))
         * math.cos(math.radians(lat2))
         * math.sin(d_lon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ── Placeholder model ─────────────────────────────────────────────────────────

def _placeholder_hospital_match(
    incident: IncidentData,
    severity: SeverityResult,
    insurance_id: str | None = None,
) -> Hospital:
    """
    Score all hospitals and return the best match.

    Scoring (weights sum to 1.0):
      distance  : 0.40 — closer is better (score = 1 / (1 + distance_km))
      beds      : 0.30 — more beds = higher score (normalised 0–1)
      specialty : 0.20 — exact specialty match = 1.0, general fallback = 0.4
      insurance : 0.10 — match = 1.0, no match = 0.0

    [REPLACE] with ML ranking model on SageMaker or a weighted query in RDS.
    """
    care_type_str = severity.care_type.value   # e.g. "cardiac"
    scene_lat = incident.latitude
    scene_lon = incident.longitude
    max_beds = max(h["available_beds"] for h in HOSPITAL_DB) or 1

    scored: list[Hospital] = []
    for h in HOSPITAL_DB:
        if h["available_beds"] == 0:
            continue  # skip full hospitals

        dist = _haversine_km(scene_lat, scene_lon, h["latitude"], h["longitude"])
        dist_score = 1 / (1 + dist)

        bed_score = h["available_beds"] / max_beds

        if care_type_str in h["specialties"]:
            spec_score = 1.0
        elif "general" in h["specialties"]:
            spec_score = 0.4
        else:
            spec_score = 0.0

        ins_score = 0.0
        if insurance_id:
            ins_code = insurance_id.upper()[:4]
            ins_score = 1.0 if any(ins_code in a for a in h["accepts_insurance"]) else 0.0
        else:
            ins_score = 0.5  # unknown — neutral

        total = (0.40 * dist_score
                 + 0.30 * bed_score
                 + 0.20 * spec_score
                 + 0.10 * ins_score)

        hospital = Hospital(**h, distance_km=round(dist, 2), score=round(total, 4))
        scored.append(hospital)
        log.debug(
            "[Router] %s | dist=%.1fkm | beds=%d | spec=%.1f | ins=%.1f | total=%.3f",
            h["name"], dist, h["available_beds"], spec_score, ins_score, total,
        )

    if not scored:
        raise RuntimeError("No hospitals with available beds found.")

    best = max(scored, key=lambda h: h.score)
    log.info("[Router] Best hospital: %s (score=%.3f, %.1f km)", best.name, best.score, best.distance_km)
    return best


def _send_prenotification(hospital: Hospital, severity: SeverityResult, eta_minutes: float | None):
    """
    [PLACEHOLDER] Log a prenotification to the hospital.
    [REPLACE] with:
        boto3 SNS publish to hospital's topic ARN, or
        HTTP POST to hospital's receiving API endpoint.
    """
    eta_str = f"~{eta_minutes:.0f} min" if eta_minutes else "unknown ETA"
    msg = (
        f"ABDM PRENOTIFICATION → {hospital.name}\n"
        f"  Severity:  Level {severity.severity_score.value} ({severity.severity_score.name})\n"
        f"  Care type: {severity.care_type.upper()}\n"
        f"  Stability: {severity.stability_window}\n"
        f"  Resources: {', '.join(severity.resources_needed)}\n"
        f"  ETA:       {eta_str}\n"
    )
    print(f"\n[PRENOTIFICATION] 📡 Sent to {hospital.name}:\n{msg}")
    log.info("[Router] Prenotification sent to %s", hospital.name)


# ── Agent entry ───────────────────────────────────────────────────────────────

async def run(
    session_id: str,
    incident: IncidentData,
    severity: SeverityResult,
    eta_minutes: float | None = None,
) -> RoutingResult:
    """
    Hospital Router Agent main entry point.
    Returns a RoutingResult with the selected hospital and QR path.
    """
    log.info("[Router] Starting for session %s | care=%s", session_id, severity.care_type)

    loop = asyncio.get_event_loop()

    # ── Select hospital ───────────────────────────────────────────────────────
    hospital: Hospital = await loop.run_in_executor(
        None, _placeholder_hospital_match, incident, severity, incident.insurance_id
    )

    print(f"\n[ROUTING] 🏥 Best match: {hospital.name}")
    print(f"[ROUTING]    Distance: {hospital.distance_km} km | Score: {hospital.score:.3f} | Beds: {hospital.available_beds}")
    print(f"[ROUTING]    Specialties: {', '.join(hospital.specialties)}")
    print(f"[ROUTING] ⚠  Placeholder model — replace with SageMaker / RDS query")

    # ── Send prenotification ──────────────────────────────────────────────────
    await loop.run_in_executor(None, _send_prenotification, hospital, severity, eta_minutes)

    # ── Generate QR code ──────────────────────────────────────────────────────
    case_payload = {
        "session_id":    session_id,
        "hospital":      hospital.model_dump(),
        "severity":      severity.model_dump(),
        "incident":      incident.model_dump(),
        "generated_at":  __import__("time").time(),
    }
    qr_path = await loop.run_in_executor(None, generate_qr, session_id, case_payload)
    print(f"[ROUTING] 📲 QR code saved: {qr_path}")

    result = RoutingResult(
        hospital=hospital,
        prenotification_sent=True,
        qr_path=qr_path,
    )
    log.info("[Router] Complete. hospital=%s qr=%s", hospital.name, qr_path)
    return result
