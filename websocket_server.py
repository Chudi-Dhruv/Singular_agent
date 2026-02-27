"""
websocket_server.py
===================
WebSocket endpoint that replaces the PyAudio mic/speaker loop entirely.

Protocol (browser ↔ server):
─────────────────────────────────────────────────────────────────────
  Browser → Server:
    binary frame     Raw PCM16 mono 16kHz audio chunks (while user speaks)
    text "READY"     Browser is ready to receive agent audio (first message)
    text "END"       User finished speaking (VAD or button release)

  Server → Browser:
    text  {"type":"transcript","text":"...","final":true/false}
    text  {"type":"agent_text","text":"..."}
    text  {"type":"state","state":"INTAKE_IN_PROGRESS"}
    text  {"type":"summary","data":{...}}
    text  {"type":"error","message":"..."}
    binary frame     Raw PCM16 mono 16kHz Polly audio (agent speaking)
─────────────────────────────────────────────────────────────────────

One WebSocket connection = one emergency session.
The full orchestrator pipeline runs inside the connection handler.
"""

import asyncio
import json
import logging
import uuid

from fastapi import WebSocket, WebSocketDisconnect

from models import IncidentData, SessionState
from tools.transcribe_tool import TranscribeSession
from tools.polly_tool import synthesize
from tools.dynamo_tool import save_session, load_session
from tools import bedrock_tool, location_tool
import agents.dispatch_agent  as dispatch_agent
import agents.severity_agent  as severity_agent
import agents.hospital_router as hospital_router
from models import IncidentSession

log = logging.getLogger(__name__)

# How long to wait for the browser to send audio before timing out a turn
TURN_TIMEOUT_S = 30


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _send_json(ws: WebSocket, obj: dict):
    await ws.send_text(json.dumps(obj))


async def _send_audio(ws: WebSocket, pcm_bytes: bytes):
    """Send Polly PCM bytes to browser in 4KB chunks to avoid frame size issues."""
    CHUNK = 4096
    for i in range(0, len(pcm_bytes), CHUNK):
        await ws.send_bytes(pcm_bytes[i : i + CHUNK])
    # Sentinel: empty binary frame signals end of agent audio
    await ws.send_bytes(b"")


async def _agent_speak(ws: WebSocket, text: str):
    """Synthesize with Polly, send to browser, and echo text to UI."""
    log.info("[WS] Agent: %s", text)
    await _send_json(ws, {"type": "agent_text", "text": text})
    pcm = await asyncio.get_event_loop().run_in_executor(None, synthesize, text)
    await _send_audio(ws, pcm)


async def _listen_turn(ws: WebSocket, session: IncidentSession) -> str:
    """
    Collect one caller turn:
      1. Wait for browser to send audio chunks (binary frames)
      2. Stream them to Transcribe
      3. Return final transcript when browser sends "END"

    Returns empty string on timeout or disconnect.
    """
    transcribe = TranscribeSession()
    await transcribe.start()

    final_text = ""
    await _send_json(ws, {"type": "listening", "state": "started"})

    try:
        while True:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=TURN_TIMEOUT_S)
            except asyncio.TimeoutError:
                log.warning("[WS] Caller turn timed out after %ds", TURN_TIMEOUT_S)
                break

            if message["type"] == "websocket.disconnect":
                log.info("[WS] Client disconnected during listen.")
                break

            if "bytes" in message and message["bytes"]:
                # Audio chunk from browser mic
                await transcribe.send_audio(message["bytes"])

            elif "text" in message:
                if message["text"] == "END":
                    # Browser signals user stopped speaking
                    log.info("[WS] Browser sent END — finishing transcription.")
                    break

    except WebSocketDisconnect:
        pass
    finally:
        final_text = await transcribe.finish()

    await _send_json(ws, {"type": "transcript", "text": final_text, "final": True})
    return final_text


# ── Main WebSocket handler ─────────────────────────────────────────────────────

async def handle_session(ws: WebSocket):
    """
    Full incident pipeline over one WebSocket connection.
    Mounted at /ws in main.py.
    """
    await ws.accept()
    session_id = str(uuid.uuid4())[:8].upper()
    session = IncidentSession(session_id=session_id)
    log.info("[WS] New session: %s", session_id)

    await _send_json(ws, {"type": "state", "state": "INTAKE_IN_PROGRESS", "session_id": session_id})

    incident = session.incident
    conversation_history: list[dict] = []
    location_callback_fired = False
    dispatch_task = None
    MAX_TURNS = 12

    try:
        # ── Wait for browser "READY" signal ──────────────────────────────────
        first = await ws.receive()
        if first.get("text") != "READY":
            log.warning("[WS] Expected READY, got: %s", first)

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 1 — INTAKE (voice conversation loop)
        # ══════════════════════════════════════════════════════════════════════
        turn = 0
        while not incident.is_complete() and turn < MAX_TURNS:
            turn += 1
            missing = incident.missing_required_fields()
            log.info("[WS] Turn %d | missing: %s", turn, missing)

            # Generate and speak agent question
            agent_text = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: bedrock_tool.generate_agent_response(
                    conversation_history, missing, is_first_turn=(turn == 1)
                ),
            )
            await _agent_speak(ws, agent_text)
            conversation_history.append({"role": "assistant", "content": agent_text})

            # Listen to caller
            caller_text = await _listen_turn(ws, session)
            if not caller_text or not caller_text.strip():
                turn -= 1
                continue
            conversation_history.append({"role": "user", "content": caller_text})

            # Extract structured fields from caller speech
            current_dict = {k: v for k, v in incident.model_dump().items() if v is not None}
            extracted = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: bedrock_tool.extract_incident_fields(caller_text, current_dict),
            )
            log.info("[WS] Extracted: %s", extracted)

            for field, value in extracted.items():
                if hasattr(incident, field) and value is not None:
                    setattr(incident, field, value)

            # Geocode if we just got a location
            if incident.location_raw and incident.latitude is None:
                lat, lon = await asyncio.get_event_loop().run_in_executor(
                    None, location_tool.geocode, incident.location_raw
                )
                incident.latitude = lat
                incident.longitude = lon

            # ── Fire dispatch in parallel the moment location is confirmed ───
            if (
                not location_callback_fired
                and incident.latitude is not None
                and incident.longitude is not None
            ):
                location_callback_fired = True
                await _send_json(ws, {"type": "state", "state": "DISPATCH_IN_PROGRESS"})
                log.info("[WS] Firing parallel dispatch for (%.4f, %.4f)", incident.latitude, incident.longitude)
                dispatch_task = asyncio.create_task(
                    dispatch_agent.run(session_id, incident.latitude, incident.longitude)
                )

            await _send_json(ws, {
                "type": "intake_progress",
                "collected": {k: v for k, v in incident.model_dump().items() if v is not None},
                "missing": incident.missing_required_fields(),
            })

        # Final intake acknowledgement
        ack = (
            "Thank you. Help is on the way. The ambulance has been dispatched. "
            "Please stay with the patient and keep this line open."
        )
        await _agent_speak(ws, ack)
        session.incident = incident
        save_session(session)

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 2 — wait for dispatch to finish (it's been running in parallel)
        # ══════════════════════════════════════════════════════════════════════
        if dispatch_task:
            dispatch_result = await dispatch_task
            session.dispatch = dispatch_result
            save_session(session)
            await _send_json(ws, {
                "type": "dispatch_complete",
                "unit_id": dispatch_result.unit.unit_id,
                "eta_minutes": dispatch_result.unit.eta_minutes,
                "tracking_url": dispatch_result.tracking_url,
            })

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 3 — Severity calculation
        # ══════════════════════════════════════════════════════════════════════
        await _send_json(ws, {"type": "state", "state": "SEVERITY_CALCULATING"})
        severity = await severity_agent.run(incident)
        session.severity = severity
        save_session(session)
        await _send_json(ws, {
            "type": "severity_complete",
            "severity_score": severity.severity_score.value,
            "care_type": severity.care_type.value,
            "stability_window": severity.stability_window,
            "resources_needed": severity.resources_needed,
            "is_placeholder": severity.is_placeholder,
        })

        # ══════════════════════════════════════════════════════════════════════
        # PHASE 4 — Hospital routing
        # ══════════════════════════════════════════════════════════════════════
        await _send_json(ws, {"type": "state", "state": "ROUTING_IN_PROGRESS"})
        eta = session.dispatch.unit.eta_minutes if session.dispatch else None
        routing = await hospital_router.run(session_id, incident, severity, eta)
        session.routing = routing
        session.state = SessionState.ACTIVE_TRANSPORT
        save_session(session)

        await _send_json(ws, {
            "type": "routing_complete",
            "hospital_name": routing.hospital.name,
            "hospital_distance_km": routing.hospital.distance_km,
            "hospital_score": routing.hospital.score,
            "qr_path": routing.qr_path,
        })

        # Final summary to browser
        await _send_json(ws, {
            "type": "summary",
            "session_id": session_id,
            "incident": incident.model_dump(),
            "dispatch": session.dispatch.model_dump() if session.dispatch else None,
            "severity": severity.model_dump(),
            "routing": {
                "hospital": routing.hospital.model_dump(),
                "qr_path": routing.qr_path,
            },
        })

        await _send_json(ws, {"type": "state", "state": "ACTIVE_TRANSPORT"})
        log.info("[WS] Session %s complete.", session_id)

    except WebSocketDisconnect:
        log.info("[WS] Client disconnected — session %s", session_id)
    except Exception as exc:
        log.exception("[WS] Unhandled error in session %s: %s", session_id, exc)
        try:
            await _send_json(ws, {"type": "error", "message": str(exc)})
        except Exception:
            pass
