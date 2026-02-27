"""
agents/intake_agent.py
INTAKE AGENT
============
Runs the voice conversation with the bystander.

Flow:
  1. Greet → ask for location
  2. Listen → extract fields via Bedrock
  3. If location now known → fire location_confirmed callback (triggers Dispatch in parallel)
  4. Continue asking until all required fields collected
  5. Return completed IncidentData

The agent will re-ask in a different phrasing if a field hasn't been provided after 2 turns.
"""

import asyncio
import logging
import time

from models import IncidentData
from tools import bedrock_tool, polly_tool, transcribe_tool

log = logging.getLogger(__name__)

MAX_TURNS = 12   # hard cap to avoid infinite loops


async def run(
    session_id: str,
    on_location_confirmed,   # async callable(lat, lon) → None  (fires dispatch)
) -> IncidentData:
    """
    Main entry point for the Intake Agent.
    `on_location_confirmed` is called once — the moment we have lat/lon.
    Returns a completed IncidentData.
    """
    incident = IncidentData()
    conversation_history: list[dict] = []
    location_callback_fired = False
    turn = 0

    log.info("[Intake] Agent starting for session %s", session_id)

    while not incident.is_complete() and turn < MAX_TURNS:
        turn += 1
        missing = incident.missing_required_fields()
        log.info("[Intake] Turn %d | missing: %s", turn, missing)

        # ── Generate agent response ──────────────────────────────────────────
        agent_text = bedrock_tool.generate_agent_response(
            conversation_history=conversation_history,
            missing_fields=missing,
            is_first_turn=(turn == 1),
        )
        print(f"\n[AGENT] {agent_text}")
        polly_tool.speak(agent_text)

        # ── Record conversation turn (assistant side) ────────────────────────
        conversation_history.append({"role": "assistant", "content": agent_text})

        # ── Listen to caller ─────────────────────────────────────────────────
        print("[Listening... speak now]")
        # Run blocking mic capture in thread pool so we don't block the event loop
        loop = asyncio.get_event_loop()
        caller_text = await loop.run_in_executor(None, transcribe_tool.listen_once)

        if not caller_text.strip():
            log.info("[Intake] No speech detected, reprompting.")
            continue

        print(f"[CALLER] {caller_text}")
        conversation_history.append({"role": "user", "content": caller_text})

        # ── Extract fields from what caller said ─────────────────────────────
        current_dict = {
            k: v for k, v in incident.model_dump().items() if v is not None
        }
        extracted = bedrock_tool.extract_incident_fields(caller_text, current_dict)
        log.info("[Intake] Extracted fields: %s", extracted)

        # Merge extracted fields into incident (only non-None values)
        for field, value in extracted.items():
            if hasattr(incident, field) and value is not None:
                setattr(incident, field, value)

        # ── Resolve geocoords if we have a location string ───────────────────
        if incident.location_raw and incident.latitude is None:
            from tools.location_tool import geocode
            lat, lon = geocode(incident.location_raw)
            incident.latitude = lat
            incident.longitude = lon

        # ── Fire dispatch callback once location is confirmed ────────────────
        if (
            not location_callback_fired
            and incident.latitude is not None
            and incident.longitude is not None
        ):
            location_callback_fired = True
            log.info(
                "[Intake] Location confirmed (%.4f, %.4f) — firing dispatch callback.",
                incident.latitude, incident.longitude,
            )
            # Fire-and-forget: dispatch runs in parallel while intake continues
            asyncio.create_task(on_location_confirmed(incident.latitude, incident.longitude))

    if not incident.is_complete():
        log.warning("[Intake] Hit MAX_TURNS (%d) before all fields collected.", MAX_TURNS)

    # Final acknowledgement to caller
    ack = (
        "Thank you. Help is on the way. The ambulance is being dispatched right now. "
        "Please stay with the patient and keep the line open."
    )
    print(f"\n[AGENT] {ack}")
    polly_tool.speak(ack)

    log.info("[Intake] Complete. incident=%s", incident.model_dump())
    return incident
