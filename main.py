"""
main.py
========
Two entry points in one file:

  1. FastAPI app  — exposes REST endpoints (session status, paramedic update, live tracking stub)
     Run with:  uvicorn main:app --reload

  2. CLI runner   — simulates a call and runs the full pipeline directly
     Run with:  python main.py

On startup the FastAPI app ensures DynamoDB table exists.
"""

import asyncio
import logging
import sys
import uuid

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import settings
from models import IncidentSession, SeverityResult, SeverityLevel, CareType
from orchestrator import Orchestrator
from tools.dynamo_tool import ensure_table_exists, load_session

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ── FastAPI app ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ABDM Emergency Response API",
    description="Agentic emergency dispatch prototype",
    version="0.1.0",
)


@app.on_event("startup")
def startup():
    log.info("Startup: ensuring DynamoDB table exists...")
    ensure_table_exists()
    log.info("DynamoDB ready.")


# ── Health check ───────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "region": settings.aws_region}


# ── Session status ─────────────────────────────────────────────────────────────

@app.get("/session/{session_id}")
def get_session(session_id: str):
    session = load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump()


# ── Live tracking stub ─────────────────────────────────────────────────────────

@app.get("/track/{session_id}/{unit_id}")
def track(session_id: str, unit_id: str):
    """
    [PLACEHOLDER] Returns a stub tracking response.
    [REPLACE] Serve a small HTML page that connects to IoT Core WebSocket
              and renders the ambulance position on a Leaflet.js map.
    """
    session = load_session(session_id)
    if not session or not session.dispatch:
        raise HTTPException(status_code=404, detail="No dispatch data for this session")
    return {
        "session_id": session_id,
        "unit_id": unit_id,
        "last_known_position": {
            "latitude":  session.dispatch.unit.latitude,
            "longitude": session.dispatch.unit.longitude,
        },
        "eta_minutes": session.dispatch.unit.eta_minutes,
        "note": "PLACEHOLDER — integrate IoT Core WebSocket for real-time feed",
    }


# ── Paramedic severity update ──────────────────────────────────────────────────

class ParamedicUpdate(BaseModel):
    session_id:    str
    severity_score: int      # 1–5
    care_type:     str       # "cardiac" / "trauma" / etc.
    stability_window: str
    resources_needed: list[str]


@app.post("/paramedic/update")
async def paramedic_update(body: ParamedicUpdate):
    """
    Called from the paramedic's app after they scan the QR on scene.
    Re-triggers hospital routing with updated severity.
    """
    session = load_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        updated_severity = SeverityResult(
            severity_score=SeverityLevel(body.severity_score),
            care_type=CareType(body.care_type),
            stability_window=body.stability_window,
            resources_needed=body.resources_needed,
            confidence=1.0,   # direct paramedic assessment
            is_placeholder=False,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    orchestrator = Orchestrator(session_id=body.session_id)
    orchestrator.session = session
    await orchestrator.handle_paramedic_update(updated_severity)

    return {
        "status": "re-routed",
        "hospital": orchestrator.session.routing.hospital.name if orchestrator.session.routing else None,
        "qr_path":  orchestrator.session.routing.qr_path if orchestrator.session.routing else None,
    }


# ── CLI runner ─────────────────────────────────────────────────────────────────

async def _cli_run():
    """Run one full incident session from the command line."""
    ensure_table_exists()
    orch = Orchestrator()
    await orch.run_incident()


if __name__ == "__main__":
    if "--api" in sys.argv:
        # Run the FastAPI server
        uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
    else:
        # Run a single incident session via CLI
        asyncio.run(_cli_run())
