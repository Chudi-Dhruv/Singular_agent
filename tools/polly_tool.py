"""
tools/polly_tool.py  (SageMaker / no-PyAudio version)
======================================================
Synthesizes speech via Amazon Polly and returns raw PCM bytes.
The WebSocket server sends these bytes back to the browser for playback —
no local speakers, no PyAudio needed.

Public API:
    synthesize(text) -> bytes   raw PCM16 mono 16kHz
    speak(text)      -> None    logs only (kept for compatibility with intake_agent)
"""

import logging
import boto3
from config import settings

log = logging.getLogger(__name__)

_client = boto3.client(
    "polly",
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
)

SAMPLE_RATE = 16000


def synthesize(text: str) -> bytes:
    """
    Call Polly and return raw PCM bytes (16-bit, mono, 16kHz).
    The caller (WebSocket server) sends these to the browser.
    """
    log.info("[Polly] Synthesizing: '%s'", text[:80])
    resp = _client.synthesize_speech(
        Text=text,
        OutputFormat="pcm",
        VoiceId=settings.polly_voice_id,
        LanguageCode=settings.polly_language_code,
        SampleRate=str(SAMPLE_RATE),
    )
    audio_bytes = resp["AudioStream"].read()
    log.info("[Polly] Synthesized %d bytes.", len(audio_bytes))
    return audio_bytes


def speak(text: str) -> None:
    """
    Compatibility shim — intake_agent calls speak().
    In the browser version this is a no-op here;
    the WebSocket server intercepts and sends audio to browser instead.
    Do not remove — intake_agent imports this.
    """
    log.info("[Polly] speak() called (no-op in server mode): '%s'", text[:60])
