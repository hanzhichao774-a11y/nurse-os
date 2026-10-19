"""Compare local voice candidates by voiced pitch, not by speaker identity."""

from pathlib import Path

import numpy as np
import soundfile as sf


for path in sorted(Path('/root/autodl-tmp').glob('nurse-zhll-voice-*.wav')):
    samples, rate = sf.read(path, dtype='float32')
    frame_size = int(rate * 0.06)
    pitches = []
    for offset in range(0, len(samples) - frame_size, frame_size // 2):
        frame = samples[offset:offset + frame_size]
        if np.sqrt(np.mean(frame * frame)) < 0.015:
            continue
        frame = frame - frame.mean()
        corr = np.correlate(frame, frame, mode='full')[frame_size - 1:]
        lo = int(rate / 350)
        hi = min(int(rate / 85), len(corr))
        lag = lo + np.argmax(corr[lo:hi])
        if corr[lag] / max(corr[0], 1e-12) > 0.5:
            pitches.append(rate / lag)
    print(path.name, 'median_hz', round(float(np.median(pitches)), 1),
          'voiced_frames', len(pitches), flush=True)
