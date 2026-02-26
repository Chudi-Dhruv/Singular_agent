"""
orchestrator.py
ORCHESTRATOR
============
The master state machine that drives the entire incident pipeline.

Responsibilities:
  1. Create and persist the IncidentSession
  2. Start Intake Agent (voice conversation)
  3. Handle the on_location_confirmed callback → start Dispatch Agent in parallel
  4. On intake complete → run Severity Agent
  5. Run Hospital Router Agent
  6. Handle paramedic severity update → re-run routing

State transitions:
  IDLE
    → INTAKE_IN_PROGRESS       (on call start)
    → DISPATCH_IN_PROGRESS     (parallel, on location confirmed)
    → SEVERITY_CALCULATING     (intake complete)
    → ROUTING_IN_PROGRESS      (severity done)
    → ACTIVE_TRANSPORT         (routing done)
    → SEVERITY_UPDATED         (paramedic update)
    → ACTIVE_TRANSPORT         (re-routed)
    → COMPLETE                 (done)
"""

import asyncio
import logging
import uuid
import time

from models import IncidentSession, SessionState, SeverityResult, IncidentData
from tools.dynamo_tool import save_session, load_session
import agents.intake_agent    as intake_agent
import agents.dispatch_agent  as dispatch_agent
import agents.severity_agent  as severity_agent
import agents.hospital_router as hospital_router

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or str(uuid.uuid4())[:8].upper()
        self.session = IncidentSession(session_id=self.session_id)
        self._dispatch_task: asyncio.Task | None = None

    def _save(self):
        save_session(self.session)

    def _set_state(self, state: SessionState):
        self.session.state = state
        self._save()
        log.info("[Orchestrator] ──► State: %s", state.value)
        print(f"\n{'='*60}")
        print(f"  STATE → {state.value}")
        print(f"{'='*60}")

    # ── Dispatch callback (fired by Intake Agent the moment location confirmed) ─

    async def _on_location_confirmed(self, lat: float, lon: float):
        """
        Runs in parallel with the ongoing intake conversation.
        Starts dispatch immediately without waiting for intake to finish.
        """
        log.info("[Orchestrator] Location confirmed — starting parallel dispatch.")
        self._set_state(SessionState.DISPATCH_IN_PROGRESS)
        try:
            result = await dispatch_agent.run(self.session_id, lat, lon)
            self.session.dispatch = result
            self._save()
            print(f"\n[ORCHESTRATOR] Tracking URL: {result.tracking_url}")
        except Exception as exc:
            log.error("[Orchestrator] Dispatch failed: %s", exc, exc_info=True)

    # ── Paramedic severity update (called from FastAPI endpoint) ───────────────

    async def handle_paramedic_update(self, updated_severity: SeverityResult):
        """
        Called when a paramedic scans the QR and updates the severity.
        Re-runs hospital routing.
        """
        log.info("[Orchestrator] Paramedic severity update received.")
        self._set_state(SessionState.SEVERITY_UPDATED)
        self.session.severity = updated_severity
        self._save()

        # Re-run routing with updated severity
        self._set_state(SessionState.ROUTING_IN_PROGRESS)
        eta = self.session.dispatch.unit.eta_minutes if self.session.dispatch else None
        routing = await hospital_router.run(
            self.session_id, self.session.incident, updated_severity, eta
        )
        self.session.routing = routing
        self._set_state(SessionState.ACTIVE_TRANSPORT)
        self._save()
        print(f"\n[ORCHESTRATOR] Re-routed to: {routing.hospital.name}")

    # ── Main pipeline ──────────────────────────────────────────────────────────

    async def run_incident(self):
        """
        Full pipeline entry point. Call this once per emergency call.
        """
        print(f"\n{'#'*60}")
        print(f"  ABDM EMERGENCY SESSION: {self.session_id}")
        print(f"{'#'*60}")

        # ── Phase 0: Session creation ────────────────────────────────────────
        self._set_state(SessionState.INTAKE_IN_PROGRESS)

        # ── Phase 1: Intake + parallel Dispatch ─────────────────────────────
        # The intake agent receives a callback. When location is confirmed it
        # fires _on_location_confirmed() as an asyncio Task — dispatch begins
        # running concurrently while the conversation continues.
        incident = await intake_agent.run(
            session_id=self.session_id,
            on_location_confirmed=self._on_location_confirmed,
        )
        self.session.incident = incident
        self._save()

        # Wait for dispatch to finish if it's still running
        # (it may have already finished while intake was completing)
        if self._dispatch_task and not self._dispatch_task.done():
            log.info("[Orchestrator] Waiting for dispatch task to complete...")
            await self._dispatch_task

        # ── Phase 2: Severity calculation ─────────────────────────────────
        self._set_state(SessionState.SEVERITY_CALCULATING)
        severity = await severity_agent.run(incident)
        self.session.severity = severity
        self._save()

        # ── Phase 3: Hospital routing ──────────────────────────────────────
        self._set_state(SessionState.ROUTING_IN_PROGRESS)
        eta = self.session.dispatch.unit.eta_minutes if self.session.dispatch else None
        routing = await hospital_router.run(
            self.session_id, incident, severity, eta
        )
        self.session.routing = routing
        self._save()

        self._set_state(SessionState.ACTIVE_TRANSPORT)

        # ── Summary ────────────────────────────────────────────────────────
        self._print_summary()

    def _print_summary(self):
        s = self.session
        print(f"\n{'#'*60}")
        print(f"  SESSION SUMMARY — {self.session_id}")
        print(f"{'#'*60}")
        print(f"  Incident:      {s.incident.incident_type} | {s.incident.victim_count} victim(s)")
        print(f"  Location:      {s.incident.location_raw} ({s.incident.latitude:.4f}, {s.incident.longitude:.4f})")
        print(f"  Consciousness: {s.incident.consciousness} | Breathing: {s.incident.breathing}")
        if s.dispatch:
            print(f"  Ambulance:     {s.dispatch.unit.unit_id} | ETA ~{s.dispatch.unit.eta_minutes:.0f} min")
            print(f"  Tracking:      {s.dispatch.tracking_url}")
        if s.severity:
            print(f"  Severity:      Level {s.severity.severity_score.value} | {s.severity.care_type.upper()} | {s.severity.stability_window}")
        if s.routing:
            print(f"  Hospital:      {s.routing.hospital.name} ({s.routing.hospital.distance_km} km)")
            print(f"  QR Code:       {s.routing.qr_path}")
        print(f"{'#'*60}\n")
