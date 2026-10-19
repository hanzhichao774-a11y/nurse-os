"""Local, consented voice clone service for the young male demo patient."""

from __future__ import annotations

import io
import logging
import os
import threading
import time
import zipfile

import numpy as np
import soundfile as sf
import torch
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from qwen_tts import Qwen3TTSModel


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOGGER = logging.getLogger("nurse.voice_clone")
MODEL_PATH = os.getenv("QWEN_TTS_MODEL", "/root/autodl-tmp/qwen3-tts-base")
REFERENCE_AUDIO = os.getenv(
    "QWEN_TTS_REFERENCE_AUDIO",
    "/root/demo_backend/processed/human-reference-clone.wav",
)
REFERENCE_TEXT = os.getenv(
    "QWEN_TTS_REFERENCE_TEXT",
    "起码有空调，有独立卫浴，咱啥也没有。",
)


class TTSInput(BaseModel):
    text: str = Field(min_length=1, max_length=300)


class TTSBatchInput(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=8)


app = FastAPI(title="Nurse demo consented voice clone", docs_url=None, redoc_url=None)
model: Qwen3TTSModel | None = None
voice_prompt = None
generation_lock = threading.Lock()


@app.on_event("startup")
def load_clone_model() -> None:
    global model, voice_prompt
    started = time.monotonic()
    if not os.path.isfile(REFERENCE_AUDIO):
        raise RuntimeError(f"reference audio not found: {REFERENCE_AUDIO}")
    model = Qwen3TTSModel.from_pretrained(
        MODEL_PATH,
        device_map="cuda:0",
        dtype=torch.bfloat16,
        attn_implementation="sdpa",
    )
    voice_prompt = model.create_voice_clone_prompt(
        ref_audio=REFERENCE_AUDIO,
        ref_text=REFERENCE_TEXT,
        x_vector_only_mode=False,
    )
    # Prime CUDA kernels before health becomes ready so the first patient line
    # does not pay the one-time model warm-up cost.
    with torch.inference_mode():
        model.generate_voice_clone(
            text="嗯。",
            language="Chinese",
            voice_clone_prompt=voice_prompt,
            non_streaming_mode=True,
            max_new_tokens=64,
        )
    LOGGER.info("voice clone ready in %.2fs", time.monotonic() - started)


@app.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok" if model is not None and voice_prompt is not None else "loading"}


@app.post("/tts")
def synthesize(payload: TTSInput) -> Response:
    text = " ".join(payload.text.strip().split())
    if not text:
        raise HTTPException(400, "text is empty")
    if model is None or voice_prompt is None:
        raise HTTPException(503, "voice clone is loading")
    started = time.monotonic()
    try:
        with generation_lock, torch.inference_mode():
            waveforms, sample_rate = model.generate_voice_clone(
                text=text,
                language="Chinese",
                voice_clone_prompt=voice_prompt,
                non_streaming_mode=True,
            )
        samples = np.asarray(waveforms[0], dtype=np.float32).reshape(-1)
        if samples.size == 0 or not np.isfinite(samples).all():
            raise RuntimeError("model returned invalid audio")
        output = io.BytesIO()
        sf.write(output, samples, int(sample_rate), format="WAV", subtype="PCM_16")
        LOGGER.info(
            "generated %.2fs speech in %.2fs for %d chars",
            samples.size / int(sample_rate),
            time.monotonic() - started,
            len(text),
        )
        return Response(output.getvalue(), media_type="audio/wav", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        LOGGER.exception("voice clone generation failed")
        raise HTTPException(500, "voice generation failed") from exc


@app.post("/tts-batch")
def synthesize_batch(payload: TTSBatchInput) -> Response:
    texts = [" ".join(item.strip().split()) for item in payload.texts]
    if any(not item or len(item) > 120 for item in texts):
        raise HTTPException(400, "invalid batch text")
    if model is None or voice_prompt is None:
        raise HTTPException(503, "voice clone is loading")
    started = time.monotonic()
    try:
        with generation_lock, torch.inference_mode():
            waveforms, sample_rate = model.generate_voice_clone(
                text=texts,
                language=["Chinese"] * len(texts),
                voice_clone_prompt=voice_prompt,
                non_streaming_mode=True,
            )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_STORED) as archive:
            for index, waveform in enumerate(waveforms):
                samples = np.asarray(waveform, dtype=np.float32).reshape(-1)
                if samples.size == 0 or not np.isfinite(samples).all():
                    raise RuntimeError("model returned invalid batch audio")
                wav = io.BytesIO()
                sf.write(wav, samples, int(sample_rate), format="WAV", subtype="PCM_16")
                archive.writestr(f"{index}.wav", wav.getvalue())
        LOGGER.info("generated %d speech segments in %.2fs", len(texts), time.monotonic() - started)
        return Response(output.getvalue(), media_type="application/zip", headers={"Cache-Control": "no-store"})
    except Exception as exc:
        LOGGER.exception("voice clone batch generation failed")
        raise HTTPException(500, "voice batch generation failed") from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("QWEN_TTS_PORT", "8090")))
