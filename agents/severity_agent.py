"""
agents/severity_agent.py
SEVERITY AGENT
==============
Calculates the triage severity of the incident.

PLACEHOLDER LOGIC:
  This is a rule-based heuristic that mimics what a trained ML model would return.
  It is intentionally simple and clearly marked so you can swap in a real
  SageMaker endpoint later with zero changes to the orchestrator or other agents.

REAL INTEGRATION POINT:
  Replace `_placeholder_severity_model()` with a call to your SageMaker endpoint.
  The input/output contract is defined here and should remain stable.

Input:  IncidentData (all fields collected by intake)
Output: SeverityResult (score 1–5, care_type, stability_window, resources_needed)

Severity scale:
  1 = Critical  (immediately life-threatening)
  2 = Emergent  (potentially life-threatening)
  3 = Urgent    (serious, stable)
  4 = Semi      (non-urgent)
  5 = Non-urgent
"""

import logging
from models import IncidentData, SeverityResult, SeverityLevel, CareType

log = logging.getLogger(__name__)


# ── Placeholder model ─────────────────────────────────────────────────────────

def _placeholder_severity_model(incident: IncidentData) -> SeverityResult:
    """
    Rule-based heuristic. Returns SeverityResult.
    
    [REPLACE] with:
        import boto3
        client = boto3.client("sagemaker-runtime", ...)
        response = client.invoke_endpoint(
            EndpointName="abdm-severity-endpoint",
            ContentType="application/json",
            Body=json.dumps(incident.model_dump()),
        )
        result = json.loads(response["Body"].read())
        return SeverityResult(**result, is_placeholder=False)
    """

    score = SeverityLevel.URGENT          # default
    care  = CareType.GENERAL
    stability = "~30 min"
    resources: list[str] = ["stretcher", "IV line", "oxygen"]

    incident_type = (incident.incident_type or "").lower()
    consciousness  = (incident.consciousness or "conscious").lower()
    breathing      = (incident.breathing or "normal").lower()
    bleeding       = (incident.bleeding or "none").lower()

    # ── Consciousness overrides ──────────────────────────────────────────────
    if consciousness == "unconscious":
        score = SeverityLevel.CRITICAL
        stability = "~10 min"
        resources += ["airway management", "defibrillator"]

    elif consciousness == "semi-conscious":
        score = SeverityLevel.EMERGENT
        stability = "~15 min"

    # ── Breathing overrides ──────────────────────────────────────────────────
    if breathing == "absent":
        score = SeverityLevel.CRITICAL
        care  = CareType.TRAUMA
        stability = "< 5 min"
        resources += ["BVM", "CPR kit", "AED"]

    elif breathing == "laboured" and score.value > 2:
        score = SeverityLevel.EMERGENT
        stability = "~15 min"

    # ── Bleeding overrides ───────────────────────────────────────────────────
    if bleeding == "severe" and score.value > 2:
        score = SeverityLevel.EMERGENT
        resources += ["tourniquet", "blood bags (O-negative)"]

    # ── Incident-type speciality mapping ─────────────────────────────────────
    if incident_type in ("cardiac", "heart attack", "chest pain"):
        care = CareType.CARDIAC
        if score.value >= 3:
            score = SeverityLevel.EMERGENT
        resources = list(set(resources + ["ECG", "defibrillator", "aspirin", "nitroglycerin"]))
        stability = "~20 min"

    elif incident_type in ("accident", "crash", "collision", "trauma"):
        care = CareType.TRAUMA
        resources = list(set(resources + ["cervical collar", "backboard", "splints"]))

    elif incident_type in ("fall", "fracture"):
        care = CareType.ORTHO
        if score.value >= 4:
            score = SeverityLevel.URGENT
        resources = list(set(resources + ["splints", "pain management"]))

    elif incident_type in ("stroke", "seizure", "neuro"):
        care = CareType.NEURO
        if score.value >= 3:
            score = SeverityLevel.EMERGENT
        resources = list(set(resources + ["CT scan priority", "neuro specialist"]))
        stability = "~15 min"

    return SeverityResult(
        severity_score=score,
        care_type=care,
        stability_window=stability,
        resources_needed=resources,
        confidence=0.72,   # placeholder confidence
        is_placeholder=True,
    )


# ── Agent entry ───────────────────────────────────────────────────────────────

async def run(incident: IncidentData) -> SeverityResult:
    """
    Severity Agent main entry point.
    Calls the placeholder model (swap for SageMaker here).
    """
    log.info("[Severity] Calculating severity for: %s / %s", incident.incident_type, incident.consciousness)

    import asyncio
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _placeholder_severity_model, incident)

    severity_label = {
        1: "CRITICAL ⚠️ ",
        2: "EMERGENT 🔴",
        3: "URGENT   🟠",
        4: "SEMI     🟡",
        5: "NON-URG  🟢",
    }.get(result.severity_score.value, "?")

    print(f"\n[SEVERITY] {severity_label} | Care: {result.care_type.upper()} | Stable ~{result.stability_window}")
    print(f"[SEVERITY] Resources needed: {', '.join(result.resources_needed)}")
    print(f"[SEVERITY] ⚠  Placeholder model (confidence: {result.confidence:.0%}) — replace with SageMaker endpoint")

    log.info("[Severity] Result: score=%s care=%s stability=%s", result.severity_score, result.care_type, result.stability_window)
    return result
