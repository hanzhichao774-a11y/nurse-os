"""Stream the consented young male clone into LiveTalking audio frames."""

import io
import re
import time
import zipfile

import httpx
import numpy as np
import resampy
import soundfile as sf

from registry import register
from utils.logger import logger
from .base_tts import State
from .edge import EdgeTTS


@register("tts", "nurseclone")
class NurseCloneTTS(EdgeTTS):
    def __init__(self, opt, parent):
        super().__init__(opt, parent)
        self.server = getattr(opt, "TTS_SERVER", "http://127.0.0.1:8090").rstrip("/")

    @staticmethod
    def _segments(text: str) -> list[str]:
        clauses = re.findall(r"[^，。！？；,.!?;…]+[，。！？；,.!?;…]*", text)
        segments, current = [], ""
        for clause in clauses or [text]:
            if current and len(current) >= 8 and len(current) + len(clause) > 14:
                segments.append(current)
                current = clause
            else:
                current += clause
            if len(current) >= 18:
                segments.append(current)
                current = ""
        if current:
            if segments and len(current) < 5:
                segments[-1] += current
            else:
                segments.append(current)
        return [part for part in segments if part.strip()]

    def _request_audio(self, text: str) -> np.ndarray:
        response = httpx.post(
            f"{self.server}/tts",
            json={"text": text},
            timeout=httpx.Timeout(90.0, connect=2.0),
        )
        response.raise_for_status()
        samples, sample_rate = sf.read(io.BytesIO(response.content), dtype="float32")
        if samples.ndim > 1:
            samples = samples[:, 0]
        if sample_rate != self.sample_rate:
            samples = resampy.resample(samples, sample_rate, self.sample_rate)
        samples = np.asarray(samples, dtype=np.float32)
        if samples.size == 0 or not np.isfinite(samples).all():
            raise RuntimeError("clone service returned invalid audio")
        return samples

    def _request_batch(self, texts: list[str]) -> list[np.ndarray]:
        response = httpx.post(
            f"{self.server}/tts-batch",
            json={"texts": texts},
            timeout=httpx.Timeout(90.0, connect=2.0),
        )
        response.raise_for_status()
        result = []
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for index in range(len(texts)):
                samples, sample_rate = sf.read(io.BytesIO(archive.read(f"{index}.wav")), dtype="float32")
                if samples.ndim > 1:
                    samples = samples[:, 0]
                if sample_rate != self.sample_rate:
                    samples = resampy.resample(samples, sample_rate, self.sample_rate)
                samples = np.asarray(samples, dtype=np.float32)
                if samples.size == 0 or not np.isfinite(samples).all():
                    raise RuntimeError("clone service returned invalid batch audio")
                result.append(samples)
        return result

    def txt_to_audio(self, msg: tuple[str, dict]):
        text, textevent = msg
        started = time.monotonic()
        emitted = 0
        segments = self._segments(text)
        try:
            generated = self._request_batch(segments) if len(segments) > 1 else [self._request_audio(segments[0])]
            for segment_index, samples in enumerate(generated):
                if emitted == 0:
                    logger.info(
                        "nurse clone pcm ready in %.3fs; %d segments, first %.2fs",
                        time.monotonic() - started,
                        len(generated),
                        len(samples) / self.sample_rate,
                    )
                total = (len(samples) + self.chunk - 1) // self.chunk
                for index in range(total):
                    if self.state != State.RUNNING:
                        return
                    frame = samples[index * self.chunk:(index + 1) * self.chunk]
                    if len(frame) < self.chunk:
                        frame = np.pad(frame, (0, self.chunk - len(frame)))
                    event = {"text": text, **textevent}
                    if emitted == 0:
                        event["status"] = "start"
                    is_final = segment_index == len(segments) - 1 and index == total - 1
                    if is_final and emitted > 0:
                        event["status"] = "end"
                    self.parent.put_audio_frame(frame, event)
                    emitted += 1
            if emitted == 1:
                self.parent.put_audio_frame(
                    np.zeros(self.chunk, dtype=np.float32),
                    {"text": text, **textevent, "status": "end"},
                )
        except Exception:
            logger.exception("nurse clone segment failed")
            if emitted:
                self.parent.put_audio_frame(
                    np.zeros(self.chunk, dtype=np.float32),
                    {"text": text, **textevent, "status": "end"},
                )
                return
            logger.warning("using young male Edge voice fallback")
            return super().txt_to_audio(msg)
