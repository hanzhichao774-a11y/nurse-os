"""Lay generated narration back onto the fixed promo picture edit."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VIDEO = Path("/Users/zhichao.han/Downloads/护语者宣传片 (1).mp4")
VOICE_DIR = ROOT / "artifacts" / "promo_voiceover"
MANIFEST = VOICE_DIR / "manifest.json"
MUSIC = ROOT / "artifacts" / "promo_stems" / "htdemucs" / "promo_original_audio" / "no_vocals.wav"
NARRATION = ROOT / "artifacts" / "护语者宣传片-自然配音-旁白.wav"
MIX = ROOT / "artifacts" / "护语者宣传片-自然配音-混音.wav"
OUTPUT = ROOT / "artifacts" / "护语者宣传片-自然配音版.mp4"

# Two lines are continuations of the previous sentence.  Starting them just
# after the prior generated waveform preserves natural cadence and still lands
# before the next visual beat.
START_OVERRIDES = {"06": 24.25, "13": 51.50}


data = json.loads(MANIFEST.read_text(encoding="utf-8"))
segments = data["segments"]
inputs: list[str] = []
filters: list[str] = []
mix_labels: list[str] = []
for index, item in enumerate(segments):
    path = VOICE_DIR / f"segment_{item['id']}.wav"
    inputs += ["-i", str(path)]
    start = START_OVERRIDES.get(item["id"], float(item["start"]))
    delay = round(start * 1000)
    label = f"v{index}"
    filters.append(
        f"[{index}:a]aresample=48000,"
        "silenceremove=start_periods=1:start_silence=0.08:start_threshold=-48dB,"
        f"asetpts=N/SR/TB,highpass=f=65,adelay={delay}:all=1[{label}]"
    )
    mix_labels.append(f"[{label}]")
filters.append(
    "".join(mix_labels)
    + f"amix=inputs={len(segments)}:normalize=0:dropout_transition=0,"
      "loudnorm=I=-16:TP=-1.5:LRA=7[narration]"
)
subprocess.run(
    [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[narration]", "-ar", "48000", "-ac", "2", str(NARRATION),
    ],
    check=True,
)

# Keep the separated music/effects bed subtle under the narration.  A gentle
# final limiter protects the AAC encode without flattening sentence dynamics.
subprocess.run(
    [
        "ffmpeg", "-y", "-i", str(NARRATION), "-i", str(MUSIC),
        "-filter_complex",
        "[1:a]aresample=48000,volume=1.35[bed];"
        "[0:a][bed]amix=inputs=2:normalize=0:duration=longest,"
        "alimiter=limit=0.891:attack=5:release=80[mix]",
        "-map", "[mix]", "-ar", "48000", "-ac", "2", str(MIX),
    ],
    check=True,
)

subprocess.run(
    [
        "ffmpeg", "-y", "-i", str(VIDEO), "-i", str(MIX),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", "61", "-movflags", "+faststart", str(OUTPUT),
    ],
    check=True,
)

print(OUTPUT)
