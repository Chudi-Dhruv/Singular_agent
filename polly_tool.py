"""
tools/polly_tool.py
Convert agent text to speech using Amazon Polly and play it through the system speaker.

Uses:
  - boto3 Polly for synthesis
  - PyAudio for playback (no temp files — stream directly from PCM bytes)
"""

import io
import logging
import boto3
import pyaudio

from config import settings

log = logging.getLogger(__name__)

_client = boto3.client(
    "polly",
    region_name=settings.aws_region,
    aws_access_key_id=settings.aws_access_key_id,
    aws_secret_access_key=settings.aws_secret_access_key,
)

# PyAudio constants for PCM playback
FORMAT   = pyaudio.paInt16
CHANNELS = 1
RATE     = 16000
CHUNK    = 1024


def speak(text: str) -> None:
    """
    Synthesize text with Polly and play it through the speaker synchronously.
    Blocks until audio finishes playing.
    """
    log.info("[Polly] Speaking: '%s'", text[:80])

    resp = _client.synthesize_speech(
        Text=text,
        OutputFormat="pcm",
        VoiceId=settings.polly_voice_id,
        LanguageCode=settings.polly_language_code,
        SampleRate=str(RATE),
    )

    audio_bytes = resp["AudioStream"].read()

    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        output=True,
        frames_per_buffer=CHUNK,
    )

    try:
        # Feed PCM in chunks so playback starts immediately
        buf = io.BytesIO(audio_bytes)
        while True:
            data = buf.read(CHUNK * 2)   # 2 bytes per sample for paInt16
            if not data:
                break
            stream.write(data)
    finally:
        stream.stop_stream()
        stream.close()
        pa.terminate()

    log.info("[Polly] Playback complete.")
