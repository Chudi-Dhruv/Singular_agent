"""
tools/bedrock_tool.py
Thin wrapper around Amazon Bedrock → Claude.

Two public functions:
  extract_incident_fields(transcript, current_data) → dict of parsed fields
  generate_agent_response(conversation_history, missing_fields) → str (next question to ask)
"""

import json
import logging
import boto3
from config import settings

log = logging.getLogger(__name__)

_client = boto3.client(
    "bedrock-runtime",
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
)
MODEL = settings.bedrock_model_id

# ── Prompts ────────────────────────────────────────────────────────────────────

EXTRACTION_SYSTEM = """You are an emergency dispatch assistant.
Your job is to extract structured information from what a caller said during an emergency call.

Extract ONLY what the caller explicitly said. Return a JSON object with these keys:
{
  "location_raw": "verbatim location or landmark they mentioned",
  "victim_count": <integer or null>,
  "incident_type": "accident|cardiac|fall|burn|assault|drowning|other or null",
  "consciousness": "conscious|unconscious|semi-conscious or null",
  "breathing": "normal|laboured|absent or null",
  "bleeding": "none|minor|severe or null",
  "visible_injuries": "brief description or null",
  "age_estimate": "description or null",
  "insurance_id": "ID if mentioned or null"
}

Return ONLY the JSON object. No explanation, no markdown fences."""

CONVERSATION_SYSTEM = """You are ABDM, a calm, compassionate emergency dispatch voice agent in India.
You are on a live call with a bystander at an emergency scene.
Your job: collect the missing information by asking ONE natural, conversational question at a time.
Keep responses SHORT (under 25 words). Be direct. Reassure briefly. Speak as if talking normally — no lists.

If the caller seems panicked, calm them with one short sentence before asking.
Never ask for information already provided."""


def extract_incident_fields(transcript: str, current_data: dict) -> dict:
    """
    Parse the latest transcript turn and return a dict of any newly found fields.
    Only returns fields that were actually found (values won't be None).
    """
    prompt = (
        f"Already collected:\n{json.dumps(current_data, indent=2)}\n\n"
        f"Latest caller message:\n\"{transcript}\"\n\n"
        "Extract any NEW fields from the caller message. "
        "If a field was already collected, do not include it again."
    )
    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 512,
        "system": EXTRACTION_SYSTEM,
        "messages": [{"role": "user", "content": prompt}],
    }
    resp = _client.invoke_model(
        modelId=MODEL,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    raw = json.loads(resp["body"].read())["content"][0]["text"].strip()
    try:
        extracted = json.loads(raw)
        # Filter out null values so we don't overwrite existing data with None
        return {k: v for k, v in extracted.items() if v is not None}
    except json.JSONDecodeError:
        log.warning("Bedrock extraction returned non-JSON: %s", raw)
        return {}


def generate_agent_response(
    conversation_history: list[dict],
    missing_fields: list[str],
    is_first_turn: bool = False,
) -> str:
    """
    Given the conversation so far and what's still missing,
    generate the next thing the agent should say.
    """
    field_hints = {
        "location_raw": "where they are (nearest landmark, area, or address)",
        "victim_count": "how many people are injured",
        "incident_type": "what kind of emergency (accident, heart attack, fall, etc.)",
        "consciousness": "if the person is conscious / awake",
        "breathing": "if the person is breathing",
        "bleeding": "if there is any bleeding",
    }
    missing_desc = ", ".join(field_hints.get(f, f) for f in missing_fields[:2])

    system_extra = ""
    if is_first_turn:
        system_extra = "Start by introducing yourself briefly as ABDM emergency services and ask for their location."
    else:
        system_extra = f"The next most important missing information is: {missing_desc}. Ask about ONE of these."

    messages = conversation_history[-6:]  # Keep last 3 turns for context

    body = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 128,
        "system": CONVERSATION_SYSTEM + "\n\n" + system_extra,
        "messages": messages,
    }
    resp = _client.invoke_model(
        modelId=MODEL,
        body=json.dumps(body),
        contentType="application/json",
        accept="application/json",
    )
    return json.loads(resp["body"].read())["content"][0]["text"].strip()
