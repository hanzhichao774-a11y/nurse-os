"""Generate local-voice fallback lines that match the visible patient replies."""

from pathlib import Path
import os
import sys

import numpy as np
import sherpa_onnx
import soundfile as sf

from case_fallback import RESPONSES


sys.path.insert(0, '/root/LiveTalking')
from tts.nurse_local import load_model


root = Path(__file__).resolve().parent / 'assets' / 'fallback_audio' / 'local'
root.mkdir(parents=True, exist_ok=True)
model = load_model()
for category, (reply, _) in RESPONSES.items():
    generation = sherpa_onnx.GenerationConfig()
    generation.sid = int(os.getenv('NURSE_TTS_SPEAKER', '2'))
    generation.speed = float(os.getenv('NURSE_TTS_SPEED', '1.0'))
    audio = model.generate(reply, generation)
    if audio.sample_rate != 16000 or len(audio.samples) == 0:
        raise RuntimeError(f'Invalid synthesis for {category}')
    target = root / f'{category}.wav'
    sf.write(target, np.asarray(audio.samples, dtype=np.float32), 16000, subtype='PCM_16')
    print(category, target.stat().st_size, flush=True)
