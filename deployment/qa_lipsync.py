"""Coarse audio/mouth onset check for a short WebRTC recording.

This detects gross timing mistakes; it is not a phoneme-level lip-sync metric.
"""

import array
import json
import math
from pathlib import Path
import subprocess
import sys


ffmpeg = '/tmp/nurse-ffmpeg/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
source = Path(sys.argv[1] if len(sys.argv) > 1 else 'artifacts/数字人同步修复复验.webm')


def decode(*options):
    proc = subprocess.run([ffmpeg, '-v', 'error', '-i', str(source), *options],
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
    return proc.stdout


# This rectangle is the lower face in the fixed 1280 x 680 WHEP source.
width, height = 130, 65
video = decode('-map', '0:v:0', '-vf', 'crop=130:65:460:305,format=gray',
               '-f', 'rawvideo', '-')
frame_bytes = width * height
dark = []
for offset in range(0, len(video) - frame_bytes + 1, frame_bytes):
    frame = video[offset:offset + frame_bytes]
    dark.append(sum(pixel < 75 for pixel in frame) / frame_bytes)

audio_bytes = decode('-map', '0:a:0', '-ac', '1', '-ar', '16000',
                     '-f', 's16le', '-')
audio = array.array('h')
audio.frombytes(audio_bytes)
samples_per_frame = 640
rms = []
for offset in range(0, len(audio) - samples_per_frame + 1, samples_per_frame):
    chunk = audio[offset:offset + samples_per_frame]
    rms.append(math.sqrt(sum(sample * sample for sample in chunk) / len(chunk)) / 32768)

size = min(len(dark), len(rms))
dark, rms = dark[:size], rms[:size]
quiet = dark[:min(75, len(dark))]
baseline = sorted(quiet)[len(quiet) // 2]
mouth = [max(0, value - baseline) for value in dark]


def correlation(lag):
    pairs = [(mouth[i], rms[i + lag]) for i in range(size)
             if 0 <= i + lag < size]
    if not pairs:
        return 0.0
    xs, ys = zip(*pairs)
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    numerator = sum((x - mx) * (y - my) for x, y in pairs)
    denominator = math.sqrt(sum((x - mx) ** 2 for x in xs) *
                            sum((y - my) ** 2 for y in ys))
    return numerator / denominator if denominator else 0.0


lags = {lag: correlation(lag) for lag in range(-15, 16)}
best = max(lags, key=lags.get)
voice_onset = next((index / 25 for index, value in enumerate(rms) if
                    value > 0.025 and sum(x > 0.025 for x in rms[index:index + 8]) >= 4), None)
result = {
    'video_frames': len(dark),
    'audio_frames': len(rms),
    'voice_onset_seconds': voice_onset,
    'best_mouth_audio_lag_ms': best * 40,
    'best_correlation': round(lags[best], 3),
    'zero_lag_correlation': round(lags[0], 3),
    'note': 'Coarse mouth aperture proxy only; inspect recording for phoneme quality.',
}
print(json.dumps(result, ensure_ascii=False, indent=2))
