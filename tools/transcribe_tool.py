"""
tools/transcribe_tool.py
Injects a custom endpoint resolver to fix the DNS bug in amazon-transcribe 0.6.2.
"""

import asyncio
import logging
from config import settings

log = logging.getLogger(__name__)

TRANSCRIBE_REGION = settings.transcribe_region  # eu-west-1


# ── Custom endpoint resolver ──────────────────────────────────────────────────

from amazon_transcribe.endpoints import BaseEndpointResolver

class _FixedEndpointResolver(BaseEndpointResolver):
    """Always returns the correct eu-west-1 Transcribe Streaming endpoint."""
    async def resolve(self, region):
        endpoint = f"https://transcribestreaming.{TRANSCRIBE_REGION}.amazonaws.com"
        log.info("[Transcribe] Resolved endpoint → %s", endpoint)
        return endpoint


# ── Transcribe session ────────────────────────────────────────────────────────

from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent


class _ResultHandler(TranscriptResultStreamHandler):
    def __init__(self, stream, out_queue: asyncio.Queue):
        super().__init__(stream)
        self._q = out_queue
        self.final_text = ""

    async def handle_transcript_event(self, event: TranscriptEvent):
        for result in event.transcript.results:
            text = " ".join(
                alt.transcript for alt in result.alternatives if alt.transcript
            )
            if not result.is_partial:
                self.final_text += " " + text
                await self._q.put(("final", text.strip()))
            else:
                await self._q.put(("partial", text.strip()))


class TranscribeSession:
    def __init__(self):
        self._client = TranscribeStreamingClient(
            region=TRANSCRIBE_REGION,
            endpoint_resolver=_FixedEndpointResolver(),
        )
        self._stream = None
        self._handler = None
        self._result_queue: asyncio.Queue = asyncio.Queue()
        self._handler_task = None

    async def start(self):
        self._stream = await self._client.start_stream_transcription(
            language_code=settings.transcribe_language_code,
            media_sample_rate_hz=settings.transcribe_sample_rate,
            media_encoding="pcm",
        )
        self._handler = _ResultHandler(self._stream.output_stream, self._result_queue)
        self._handler_task = asyncio.create_task(self._handler.handle_events())
        log.info("[Transcribe] Session started via custom resolver.")

    async def send_audio(self, pcm_bytes: bytes):
        await self._stream.input_stream.send_audio_event(audio_chunk=pcm_bytes)

    async def finish(self) -> str:
        await self._stream.input_stream.end_stream()
        await self._handler_task
        result = self._handler.final_text.strip()
        log.info("[Transcribe] Final: '%s'", result)
        return result
