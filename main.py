"""
main.py  (SageMaker Studio / browser-voice version)
=====================================================
Runs a FastAPI server that:
  - Serves the browser UI at  GET /
  - Handles voice sessions at  WS  /ws
  - Exposes REST endpoints for session status, paramedic update, tracking

Running on SageMaker Studio:
  uvicorn main:app --host 0.0.0.0 --port 8000

Then open the SageMaker Studio proxy URL:
  https://<domain>.studio.<region>.sagemaker.aws/jupyter/default/proxy/8000/
"""

import asyncio
import logging
import sys

import uvicorn
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from config import settings
from models import SeverityResult, SeverityLevel, CareType
from orchestrator import Orchestrator
from tools.dynamo_tool import ensure_table_exists, load_session
from websocket_server import handle_session

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="ABDM Emergency Response",
    description="Voice-first agentic emergency dispatch prototype",
    version="0.2.0",
    root_path_in_servers=False,
)

# Handle SageMaker proxy trailing slash
@app.middleware("http")
async def log_requests(request, call_next):
    import logging
    logging.getLogger("main").info("REQUEST: %s %s", request.method, request.url.path)
    response = await call_next(request)
    return response


@app.on_event("startup")
def startup():
    log.info("Startup: ensuring DynamoDB table '%s' exists...", settings.dynamo_table_name)
    ensure_table_exists()
    log.info("DynamoDB ready.")


# ── Browser UI ─────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_ui():
    """Serve the browser voice UI."""
    with open("static/index.html", "r") as f:
        return HTMLResponse(content=f.read())


# ── WebSocket — one connection = one emergency session ─────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    """
    Full voice pipeline over WebSocket.
    Browser sends mic audio → Transcribe → Claude → Polly → browser speaker.
    """
    await handle_session(ws)


# ── REST: health ───────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "region": settings.aws_region}


# ── REST: session status ───────────────────────────────────────────────────────

@app.get("/session/{session_id}")
def get_session(session_id: str):
    session = load_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session.model_dump()


# ── REST: tracking stub ────────────────────────────────────────────────────────

@app.get("/track/{session_id}/{unit_id}")
def track(session_id: str, unit_id: str):
    """
    [PLACEHOLDER] Returns last known ambulance position.
    [REPLACE] with IoT Core WebSocket → Leaflet.js tracking page.
    """
    session = load_session(session_id)
    if not session or not session.dispatch:
        raise HTTPException(status_code=404, detail="No dispatch data for session")
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


# ── REST: paramedic update → re-routing ───────────────────────────────────────

class ParamedicUpdate(BaseModel):
    session_id:       str
    severity_score:   int         # 1–5
    care_type:        str         # "cardiac" / "trauma" / etc.
    stability_window: str
    resources_needed: list[str]


@app.post("/paramedic/update")
async def paramedic_update(body: ParamedicUpdate):
    """
    Called when paramedic scans QR on scene and submits updated severity.
    Re-runs hospital routing with the real on-scene assessment.
    """
    session = load_session(body.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        updated = SeverityResult(
            severity_score=SeverityLevel(body.severity_score),
            care_type=CareType(body.care_type),
            stability_window=body.stability_window,
            resources_needed=body.resources_needed,
            confidence=1.0,
            is_placeholder=False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    orch = Orchestrator(session_id=body.session_id)
    orch.session = session
    await orch.handle_paramedic_update(updated)

    return {
        "status": "re-routed",
        "hospital": orch.session.routing.hospital.name if orch.session.routing else None,
        "qr_path":  orch.session.routing.qr_path if orch.session.routing else None,
    }


# ── Entry point ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
