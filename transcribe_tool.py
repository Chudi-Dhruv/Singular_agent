"""
tools/transcribe_tool.py
Capture audio from the microphone and stream it to Amazon Transcribe Streaming.
Returns the final transcript for one "turn" (caller stops speaking → silence detected).

Uses:
  - PyAudio for mic capture
  - amazon-transcribe SDK for streaming STT
"""

import asyncio
import logging
import queue
import threading
import time

import pyaudio
from amazon_transcribe.client import TranscribeStreamingClient
from amazon_transcribe.handlers import TranscriptResultStreamHandler
from amazon_transcribe.model import TranscriptEvent

from config import settings

log = logging.getLogger(__name__)

# Audio settings — must match Transcribe expectations
CHUNK      = 1024 * 2   # bytes per PyAudio read
FORMAT     = pyaudio.paInt16
CHANNELS   = 1
RATE       = settings.transcribe_sample_rate
SILENCE_S  = 2.0        # stop listening after 2 s of silence (end of caller turn)
MAX_RECORD = 30.0       # hard cap per turn


class _ResultHandler(TranscriptResultStreamHandler):
    """Collect partial + final results from the Transcribe stream."""

    def __init__(self, stream, result_queue: asyncio.Queue):
        super().__init__(stream)
        self._q = result_queue
        self.final_transcript = ""

    async def handle_transcript_event(self, event: TranscriptEvent):
        for result in event.transcript.results:
            if not result.is_partial:
                text = " ".join(
                    alt.transcript
                    for alt in result.alternatives
                    if alt.transcript
                )
                self.final_transcript += " " + text
                await self._q.put(("final", text))
            else:
                text = result.alternatives[0].transcript if result.alternatives else ""
                await self._q.put(("partial", text))


async def _stream_mic_to_transcribe() -> str:
    """Core async function: open mic, stream to Transcribe, return final text."""
    client = TranscribeStreamingClient(
        region=settings.aws_region,
        credentials={
            "access_key": settings.aws_access_key_id,
            "secret_key": settings.aws_secret_access_key,
        },
    )

    stream = await client.start_stream_transcription(
        language_code=settings.transcribe_language_code,
        media_sample_rate_hz=RATE,
        media_encoding="pcm",
    )

    result_queue: asyncio.Queue = asyncio.Queue()
    handler = _ResultHandler(stream.output_stream, result_queue)

    # PyAudio in a thread → feed chunks to the Transcribe stream
    audio_queue: queue.Queue = queue.Queue()

    def mic_worker():
        pa = pyaudio.PyAudio()
        mic = pa.open(
            format=FORMAT, channels=CHANNELS, rate=RATE,
            input=True, frames_per_buffer=CHUNK
        )
        log.info("[Transcribe] Microphone open — listening...")
        start = time.time()
        last_audio = time.time()
        try:
            while True:
                data = mic.read(CHUNK, exception_on_overflow=False)
                audio_queue.put(data)
                # Simple energy-based silence detection
                import struct, math
                samples = struct.unpack("<" + "h" * (len(data) // 2), data)
                rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                if rms > 200:   # not silent
                    last_audio = time.time()
                elapsed = time.time() - start
                silence = time.time() - last_audio
                if silence > SILENCE_S or elapsed > MAX_RECORD:
                    break
        finally:
            mic.stop_stream()
            mic.close()
            pa.terminate()
            audio_queue.put(None)  # sentinel

    mic_thread = threading.Thread(target=mic_worker, daemon=True)
    mic_thread.start()

    async def send_audio():
        loop = asyncio.get_event_loop()
        while True:
            chunk = await loop.run_in_executor(None, audio_queue.get)
            if chunk is None:
                break
            await stream.input_stream.send_audio_event(audio_chunk=chunk)
        await stream.input_stream.end_stream()

    await asyncio.gather(send_audio(), handler.handle_events())
    mic_thread.join()

    transcript = handler.final_transcript.strip()
    log.info("[Transcribe] Final transcript: '%s'", transcript)
    return transcript


def listen_once() -> str:
    """
    Blocking call: records one caller turn from the microphone,
    returns the transcript as a string.
    Call this from synchronous code.
    """
    return asyncio.run(_stream_mic_to_transcribe())
