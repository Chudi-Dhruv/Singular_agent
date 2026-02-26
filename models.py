"""
models.py
Shared Pydantic data models used across all agents.
These are the canonical data contracts for the entire pipeline.
"""

from __future__ import annotations
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field
import time


# ── Enums ──────────────────────────────────────────────────────────────────────

class SessionState(str, Enum):
    IDLE                = "IDLE"
    INTAKE_IN_PROGRESS  = "INTAKE_IN_PROGRESS"
    DISPATCH_IN_PROGRESS= "DISPATCH_IN_PROGRESS"
    SEVERITY_CALCULATING= "SEVERITY_CALCULATING"
    ROUTING_IN_PROGRESS = "ROUTING_IN_PROGRESS"
    ACTIVE_TRANSPORT    = "ACTIVE_TRANSPORT"
    SEVERITY_UPDATED    = "SEVERITY_UPDATED"
    COMPLETE            = "COMPLETE"


class CareType(str, Enum):
    TRAUMA   = "trauma"
    CARDIAC  = "cardiac"
    NEURO    = "neuro"
    ORTHO    = "ortho"
    GENERAL  = "general"


class SeverityLevel(int, Enum):
    CRITICAL  = 1   # Immediately life-threatening
    EMERGENT  = 2   # Potentially life-threatening
    URGENT    = 3   # Serious but stable
    SEMI      = 4   # Non-urgent
    NON_URGENT= 5   # Minor


# ── Incident Data (collected during intake) ────────────────────────────────────

class IncidentData(BaseModel):
    location_raw: Optional[str]   = None   # What the caller said
    latitude:     Optional[float] = None
    longitude:    Optional[float] = None
    victim_count:     Optional[int]  = None
    incident_type:    Optional[str]  = None   # accident / cardiac / fall / burn / etc.
    consciousness:    Optional[str]  = None   # conscious / unconscious / semi-conscious
    breathing:        Optional[str]  = None   # normal / laboured / absent
    bleeding:         Optional[str]  = None   # none / minor / severe
    visible_injuries: Optional[str]  = None
    age_estimate:     Optional[str]  = None
    insurance_id:     Optional[str]  = None

    def missing_required_fields(self) -> list[str]:
        """Return list of field names that are still None and are required."""
        required = [
            "location_raw", "victim_count", "incident_type",
            "consciousness", "breathing",
        ]
        return [f for f in required if getattr(self, f) is None]

    def is_complete(self) -> bool:
        return len(self.missing_required_fields()) == 0


# ── Dispatch ───────────────────────────────────────────────────────────────────

class AmbulanceUnit(BaseModel):
    unit_id:   str
    latitude:  float
    longitude: float
    eta_minutes: Optional[float] = None


class DispatchResult(BaseModel):
    unit:        AmbulanceUnit
    tracking_url: str
    dispatched_at: float = Field(default_factory=time.time)


# ── Severity ───────────────────────────────────────────────────────────────────

class SeverityResult(BaseModel):
    severity_score:    SeverityLevel
    care_type:         CareType
    stability_window:  str          # e.g. "~15 min"
    resources_needed:  list[str]    # e.g. ["ECG", "defibrillator"]
    confidence:        float        # 0.0–1.0  (placeholder always returns fixed value)
    is_placeholder:    bool = True  # flag so you know it's dummy logic


# ── Hospital ───────────────────────────────────────────────────────────────────

class Hospital(BaseModel):
    hospital_id:   str
    name:          str
    latitude:      float
    longitude:     float
    specialties:   list[str]
    available_beds: int
    accepts_insurance: list[str]   # list of insurer codes
    distance_km:   Optional[float] = None
    score:         Optional[float] = None


class RoutingResult(BaseModel):
    hospital:         Hospital
    prenotification_sent: bool
    qr_path:          Optional[str] = None
    routed_at:        float = Field(default_factory=time.time)


# ── Master Session ─────────────────────────────────────────────────────────────

class IncidentSession(BaseModel):
    session_id:    str
    caller_phone:  Optional[str]   = None
    state:         SessionState    = SessionState.IDLE
    incident:      IncidentData    = Field(default_factory=IncidentData)
    dispatch:      Optional[DispatchResult] = None
    severity:      Optional[SeverityResult] = None
    routing:       Optional[RoutingResult]  = None
    created_at:    float = Field(default_factory=time.time)
    updated_at:    float = Field(default_factory=time.time)
