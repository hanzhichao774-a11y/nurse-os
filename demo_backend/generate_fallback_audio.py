"""Regenerate the complete fallback utterances in the same voice as live speech."""

from __future__ import annotations

import asyncio
from pathlib import Path

import edge_tts
import numpy as np
import resampy
import soundfile as sf

from case_fallback import RESPONSES


OUTPUT = Path(__file__).resolve().parent / "assets" / "fallback_audio"
VOICE = "zh-CN-XiaoyiNeural"


async def generate(category: str, reply: str, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{category}.wav"
    temporary = folder / f"{category}.mp3"
    await edge_tts.Communicate(reply, VOICE, rate="-5%", pitch="-8Hz").save(str(temporary))
    samples, rate = sf.read(temporary, dtype="float32")
    if samples.ndim > 1:
        samples = samples[:, 0]
    if rate != 16000:
        samples = resampy.resample(samples, rate, 16000)
    sf.write(target, np.asarray(samples, dtype="float32"), 16000, subtype="PCM_16")
    temporary.unlink()
    print(target.relative_to(OUTPUT), f"{target.stat().st_size} bytes", flush=True)


async def main() -> None:
    for category, (reply, _) in RESPONSES.items():
        await generate(category, reply, OUTPUT)


if __name__ == "__main__":
    asyncio.run(main())
