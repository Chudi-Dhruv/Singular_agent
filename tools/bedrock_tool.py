import json
import logging
from typing import Optional
from tools.aws_client import make_client
from config import settings

log = logging.getLogger(__name__)
_client = make_client("bedrock-runtime")
MODEL   = settings.bedrock_model_id

EXTRACTION_SYSTEM = """You are an emergency dispatch assistant.
Extract structured information from what a caller said during an emergency call.

Return a JSON object with these keys (null if not mentioned):
{
  "location_raw": "verbatim location or landmark",
  "victim_count": <integer or null>,
  "incident_type": "accident|cardiac|fall|burn|assault|drowning|other or null",
  "consciousness": "conscious|unconscious|semi-conscious or null",
  "breathing": "normal|laboured|absent or null",
  "bleeding": "none|minor|severe or null",
  "visible_injuries": "brief description or null",
  "age_estimate": "description or null",
  "insurance_id": "ID if mentioned or null"
}
Return ONLY the JSON object. No explanation, no markdown."""

CONVERSATION_SYSTEM = """You are ABDM, a calm emergency dispatch voice agent in India.
You are on a live call with a bystander at an emergency scene.

CRITICAL RULES:
1. NEVER ask for information the caller has already provided.
2. If the caller gave multiple pieces of information, acknowledge them and ask only about what is STILL missing.
3. Ask ONE question at a time covering the most urgent missing field.
4. Keep responses under 30 words. Be direct and calm.
5. If only one field is missing, ask specifically about that.
6. If no fields are missing, just reassure the caller help is coming."""


def _invoke(body: dict) -> str:
    resp = _client.invoke_model(
        modelId=MODEL,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    parsed = json.loads(resp["body"].read())
    blocks = parsed.get("content", [])
    return blocks[0]["text"].strip() if blocks else ""


def generate_agent_response(
    conversation_history: list,
    missing_fields: list,
    is_first_turn: bool = False,
    session_id: Optional[str] = None,
    turn: int = 0,
) -> str:
    field_hints = {
        "location_raw":  "their exact location or nearest landmark",
        "victim_count":  "how many people are injured",
        "incident_type": "what type of emergency (accident, cardiac, fall, etc.)",
        "consciousness": "whether the patient is conscious or awake",
        "breathing":     "whether the patient is breathing",
        "bleeding":      "whether there is any bleeding",
    }

    if is_first_turn:
        system_extra = (
            "Introduce yourself briefly as ABDM emergency services. "
            "Tell the caller help is being arranged. Ask for their location."
        )
        messages = [{"role": "user", "content": "Emergency call connected."}]
    elif not missing_fields:
        system_extra = "All information collected. Reassure the caller that help is on the way."
        messages = conversation_history[-6:] or [{"role": "user", "content": "All info provided."}]
    else:
        missing_desc   = "\n".join(f"  - {field_hints.get(f, f)}" for f in missing_fields)
        already        = [f for f in field_hints if f not in missing_fields]
        collected_desc = ", ".join(already) if already else "nothing yet"
        system_extra   = (
            f"Already collected: {collected_desc}.\n"
            f"Still missing (ask about the FIRST one only):\n{missing_desc}\n\n"
            "Acknowledge anything the caller just said, then ask about the single most urgent missing item."
        )
        messages = conversation_history[-6:] or [{"role": "user", "content": "Please continue."}]

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 128,
        "system": CONVERSATION_SYSTEM + "\n\n" + system_extra,
        "messages": messages,
    }
    return _invoke(body)


def extract_incident_fields(
    transcript: str,
    current_data: dict,
    session_id: Optional[str] = None,
    turn: int = 0,
) -> dict:
    prompt = (
        f"Already collected (do not re-extract):\n{json.dumps(current_data, indent=2)}\n\n"
        f"Latest caller message:\n\"{transcript}\"\n\n"
        "Extract ALL new fields mentioned. A caller may give location, victim count, "
        "and symptoms all at once — capture all of them."
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": EXTRACTION_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }
    raw = _invoke(body)
    try:
        extracted = json.loads(raw)
        result = {k: v for k, v in extracted.items() if v is not None}
        log.info("[Bedrock] Extracted fields: %s", list(result.keys()))
        return result
    except json.JSONDecodeError:
        log.warning("[Bedrock] Non-JSON response: %s", raw)
        return {}
