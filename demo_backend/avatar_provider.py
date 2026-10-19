"""Realtime avatar providers used by the nurse training demo.

SoulX only owns rendering and playback. The case model, transcript and scoring
remain in ``app.py``. One renderer session is supported because the demo itself
is intentionally single-user.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import io
import json
import logging
import os
import re
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx


LOGGER = logging.getLogger("hu-yu-zhe.avatar")
TARGET_SAMPLE_RATE = 16_000
DEFAULT_AUDIO_LEAD_MS = 1_300
CLIENT_AUDIO_CHUNK_SAMPLES = TARGET_SAMPLE_RATE
RENDERER_AUDIO_CHUNK_SAMPLES = round(TARGET_SAMPLE_RATE * 0.16)


def wav_to_pcm16(data: bytes, target_rate: int = TARGET_SAMPLE_RATE) -> bytes:
    """Decode a PCM16 WAV and return mono PCM16 at ``target_rate``.

    The cloned voice service and cached lines currently emit 24 kHz WAV while
    SoulX consumes 16 kHz PCM. Linear interpolation is sufficient for speech
    and keeps this adapter independent from FFmpeg and scipy.
    """

    import numpy as np

    with wave.open(io.BytesIO(data), "rb") as source:
        channels = source.getnchannels()
        width = source.getsampwidth()
        source_rate = source.getframerate()
        frames = source.readframes(source.getnframes())
    if width != 2 or channels < 1:
        raise ValueError("only PCM16 WAV audio is supported")
    samples = np.frombuffer(frames, dtype="<i2")
    if channels > 1:
        samples = samples.reshape(-1, channels).astype(np.int32).mean(axis=1)
    samples = samples.astype(np.float32)
    if source_rate != target_rate and samples.size:
        output_count = max(1, round(samples.size * target_rate / source_rate))
        source_axis = np.arange(samples.size, dtype=np.float64)
        output_axis = np.arange(output_count, dtype=np.float64) * source_rate / target_rate
        samples = np.interp(output_axis, source_axis, samples)
    return np.clip(np.rint(samples), -32768, 32767).astype("<i2").tobytes()


@dataclass(slots=True)
class AudioJob:
    text: str
    wav_path: Path | None = None


class SoulXSession:
    def __init__(
        self,
        session_id: str,
        renderer_url: str,
        tts_url: str,
        audio_lead_ms: int = DEFAULT_AUDIO_LEAD_MS,
    ) -> None:
        self.session_id = session_id
        self.renderer_url = renderer_url
        self.tts_url = tts_url.rstrip("/")
        self.audio_lead_ms = audio_lead_ms
        self.browser: Any | None = None
        self.renderer: Any | None = None
        self.jobs: asyncio.Queue[AudioJob | None] = asyncio.Queue(maxsize=8)
        self.send_lock = asyncio.Lock()
        self.current_job: asyncio.Task[None] | None = None
        self.generation = 0
        self.closed = False
        self.latest_frame: bytes | None = None
        self.frame_ready = asyncio.Event()
        self.renderer_flushed = asyncio.Event()
        self.audio_ready: dict[str, asyncio.Event] = {}

    async def send_json(self, payload: dict[str, Any]) -> None:
        if self.browser is None:
            return
        async with self.send_lock:
            await self.browser.send_json(payload)

    async def send_frame(self, frame: bytes) -> None:
        if self.browser is None:
            return
        async with self.send_lock:
            await self.browser.send_bytes(frame)

    async def enqueue(self, job: AudioJob) -> bool:
        if self.closed or self.browser is None or self.renderer is None:
            return False
        try:
            self.jobs.put_nowait(job)
        except asyncio.QueueFull:
            LOGGER.warning("SoulX speech queue is full for %s", self.session_id)
            return False
        return True

    async def interrupt(self) -> None:
        self.generation += 1
        if self.current_job is not None:
            self.current_job.cancel()
        while not self.jobs.empty():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.jobs.get_nowait()
        if self.renderer is not None:
            with contextlib.suppress(Exception):
                await self.renderer.send(json.dumps({"type": "flush"}))
        with contextlib.suppress(Exception):
            await self.send_json({"type": "flush"})

    async def _read_job_audio(self, job: AudioJob) -> bytes:
        if job.wav_path is not None:
            return await asyncio.to_thread(job.wav_path.read_bytes)
        timeout = httpx.Timeout(90.0, connect=2.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(f"{self.tts_url}/tts", json={"text": job.text})
            response.raise_for_status()
            return response.content

    async def _play_job(self, job: AudioJob, generation: int) -> None:
        started = asyncio.get_running_loop().time()
        wav_data = await self._read_job_audio(job)
        pcm = await asyncio.to_thread(wav_to_pcm16, wav_data)
        if generation != self.generation or not pcm or self.renderer is None:
            return

        # SoulX renders one 0.96s block at a time.  Sending an entire response
        # here lets inference run far ahead of wall clock, fills its two-block
        # output queue and drops most mouth frames.  It is the main cause of a
        # long answer looking like a few unrelated poses.  Clear the current
        # idle block first, then pace 160ms audio pieces against a monotonic
        # clock so the renderer and WebAudio advance on the same timeline.
        self.renderer_flushed.clear()
        await self.renderer.send(json.dumps({"type": "flush"}))
        try:
            await asyncio.wait_for(self.renderer_flushed.wait(), timeout=1.0)
        except TimeoutError:
            LOGGER.warning("SoulX renderer flush acknowledgement timed out for %s", self.session_id)

        response_id = f"{self.session_id}-{generation}-{int(started * 1000)}"
        audio_ready = asyncio.Event()
        self.audio_ready[response_id] = audio_ready
        total_samples = len(pcm) // 2
        chunks = max(1, (total_samples + CLIENT_AUDIO_CHUNK_SAMPLES - 1) // CLIENT_AUDIO_CHUNK_SAMPLES)
        await self.send_json({
            "type": "audio-start",
            "response_id": response_id,
            "sample_rate": TARGET_SAMPLE_RATE,
            "lead_ms": self.audio_lead_ms,
            "duration_ms": round(total_samples * 1000 / TARGET_SAMPLE_RATE),
        })
        for index in range(chunks):
            if generation != self.generation:
                return
            begin = index * CLIENT_AUDIO_CHUNK_SAMPLES * 2
            end = min(len(pcm), (index + 1) * CLIENT_AUDIO_CHUNK_SAMPLES * 2)
            await self.send_json({
                "type": "audio",
                "response_id": response_id,
                "pcm": base64.b64encode(pcm[begin:end]).decode("ascii"),
                "final": index == chunks - 1,
            })

        # Do not animate speech until the browser confirms its AudioContext is
        # running and the exact PCM has been scheduled.  Mobile Safari can
        # suspend WebAudio; without this handshake the face would speak in
        # silence while the user is still being asked to enable sound.
        try:
            await asyncio.wait_for(audio_ready.wait(), timeout=15.0)
        except TimeoutError:
            LOGGER.warning("browser audio did not become ready for %s", self.session_id)
            await self.send_json({
                "type": "audio-error",
                "message": "请点击开启患者声音后重试",
            })
            return
        finally:
            self.audio_ready.pop(response_id, None)

        renderer_started = asyncio.get_running_loop().time()
        renderer_chunk_bytes = RENDERER_AUDIO_CHUNK_SAMPLES * 2
        for index, begin in enumerate(range(0, len(pcm), renderer_chunk_bytes)):
            if generation != self.generation or self.renderer is None:
                return
            await self.renderer.send(json.dumps({
                "type": "audio",
                "pcm": base64.b64encode(pcm[begin:begin + renderer_chunk_bytes]).decode("ascii"),
            }))
            deadline = renderer_started + (index + 1) * (
                RENDERER_AUDIO_CHUNK_SAMPLES / TARGET_SAMPLE_RATE
            )
            delay = deadline - asyncio.get_running_loop().time()
            if delay > 0:
                await asyncio.sleep(delay)
        LOGGER.info(
            "SoulX paced %.2fs audio in %.2fs for %s",
            total_samples / TARGET_SAMPLE_RATE,
            asyncio.get_running_loop().time() - started,
            self.session_id,
        )
        # Keep subsequent replies off the renderer until this one has reached
        # the listener. Interrupt cancels this wait together with the job.
        await asyncio.sleep(self.audio_lead_ms / 1000)

    async def _job_worker(self) -> None:
        while not self.closed:
            job = await self.jobs.get()
            if job is None:
                return
            generation = self.generation
            self.current_job = asyncio.create_task(self._play_job(job, generation))
            try:
                await self.current_job
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                LOGGER.exception("SoulX audio job failed for %s", self.session_id)
                with contextlib.suppress(Exception):
                    await self.send_json({"type": "audio-error", "message": str(exc)[:160]})
            finally:
                self.current_job = None

    async def _renderer_reader(self) -> None:
        assert self.renderer is not None
        async for message in self.renderer:
            if isinstance(message, bytes):
                self.latest_frame = message
                self.frame_ready.set()
                continue
            try:
                event = json.loads(message)
            except (TypeError, json.JSONDecodeError):
                continue
            if event.get("type") == "ready":
                await self.send_json({
                    "type": "ready",
                    "fps": event.get("fps", 25),
                    "audio_lead_ms": self.audio_lead_ms,
                })
            elif event.get("type") == "flushed":
                self.renderer_flushed.set()
            elif event.get("type") == "error":
                await self.send_json(event)

    async def _frame_writer(self) -> None:
        while not self.closed:
            await self.frame_ready.wait()
            frame = self.latest_frame
            self.latest_frame = None
            self.frame_ready.clear()
            if frame is not None:
                await self.send_frame(frame)

    async def _browser_reader(self) -> None:
        assert self.browser is not None
        while not self.closed:
            event = await self.browser.receive()
            if event.get("type") == "websocket.disconnect":
                return
            text = event.get("text")
            if not text:
                continue
            with contextlib.suppress(json.JSONDecodeError):
                payload = json.loads(text)
                if payload.get("type") == "interrupt":
                    await self.interrupt()
                elif payload.get("type") == "audio-ready":
                    ready = self.audio_ready.get(str(payload.get("response_id", "")))
                    if ready is not None:
                        ready.set()
                elif payload.get("type") == "ping":
                    await self.send_json({"type": "pong"})

    async def serve(self, browser: Any) -> None:
        import websockets

        self.browser = browser
        await browser.accept()
        try:
            async with websockets.connect(
                self.renderer_url,
                max_size=16 * 1024 * 1024,
                open_timeout=5,
                ping_interval=20,
                ping_timeout=20,
            ) as renderer:
                self.renderer = renderer
                tasks = [
                    asyncio.create_task(self._renderer_reader()),
                    asyncio.create_task(self._frame_writer()),
                    asyncio.create_task(self._browser_reader()),
                    asyncio.create_task(self._job_worker()),
                ]
                done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                for task in done:
                    error = task.exception()
                    if error:
                        raise error
        finally:
            self.renderer = None
            self.browser = None
            self.closed = True
            if self.current_job is not None:
                self.current_job.cancel()


class SoulXAvatarProvider:
    name = "soulx"

    def __init__(self, renderer_url: str | None = None) -> None:
        self.renderer_url = renderer_url or os.getenv("SOULX_RENDERER_URL", "ws://127.0.0.1:8791")
        self.tts_url = os.getenv("SOULX_TTS_URL", "http://127.0.0.1:8090")
        self.audio_lead_ms = int(os.getenv("SOULX_AUDIO_LEAD_MS", str(DEFAULT_AUDIO_LEAD_MS)))
        self.sessions: dict[str, SoulXSession] = {}
        self.lock = asyncio.Lock()

    async def available(self, timeout: float = 2.5) -> bool:
        import websockets

        try:
            async with asyncio.timeout(timeout):
                async with websockets.connect(self.renderer_url, open_timeout=timeout) as ws:
                    message = await ws.recv()
                    return isinstance(message, str) and json.loads(message).get("type") == "ready"
        except Exception:
            return False

    async def serve(self, session_id: str, browser: Any) -> None:
        session = SoulXSession(
            session_id,
            renderer_url=self.renderer_url,
            tts_url=self.tts_url,
            audio_lead_ms=self.audio_lead_ms,
        )
        async with self.lock:
            old = self.sessions.pop(session_id, None)
            if old is not None:
                await old.interrupt()
                old.closed = True
            self.sessions[session_id] = session
        try:
            await session.serve(browser)
        finally:
            async with self.lock:
                if self.sessions.get(session_id) is session:
                    self.sessions.pop(session_id, None)

    async def play(self, session_id: str, text: str, wav_path: Path | None = None) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            return False
        return await session.enqueue(AudioJob(text=text, wav_path=wav_path))

    async def interrupt(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session is None:
            return False
        await session.interrupt()
        return True

    async def close(self, session_id: str) -> None:
        session = self.sessions.get(session_id)
        if session is None:
            return
        await session.interrupt()
        session.closed = True


SOULX = SoulXAvatarProvider()
SOULX_WANG_AYI = SoulXAvatarProvider(
    os.getenv("SOULX_WANG_AYI_RENDERER_URL", "ws://127.0.0.1:8792")
)


def soulx_for_case(case_id: str) -> SoulXAvatarProvider:
    return SOULX_WANG_AYI if case_id == "wang_ayi" else SOULX


def valid_session_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{4}", value))
