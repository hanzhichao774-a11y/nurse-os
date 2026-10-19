"""Transcribe the uploaded actor recording for voice-reference selection."""

import json
import sys
from pathlib import Path

from faster_whisper import WhisperModel


source = Path(sys.argv[1])
output = Path(sys.argv[2])
model_name = sys.argv[3] if len(sys.argv) > 3 else "small"

try:
    model = WhisperModel(
        model_name,
        device="cuda",
        compute_type="float16",
        download_root="/root/autodl-tmp/whisper",
    )
except Exception:
    model = WhisperModel(
        model_name,
        device="cpu",
        compute_type="int8",
        download_root="/root/autodl-tmp/whisper",
    )

segments, info = model.transcribe(
    str(source),
    language="zh",
    beam_size=5,
    vad_filter=True,
    vad_parameters={"min_silence_duration_ms": 300},
    word_timestamps=True,
)

data = {
    "language": info.language,
    "language_probability": info.language_probability,
    "duration": info.duration,
    "segments": [],
}
for segment in segments:
    data["segments"].append({
        "start": round(segment.start, 3),
        "end": round(segment.end, 3),
        "text": segment.text.strip(),
        "avg_logprob": round(segment.avg_logprob, 4),
        "no_speech_prob": round(segment.no_speech_prob, 4),
    })

output.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"segments": len(data["segments"]), "output": str(output)}, ensure_ascii=False))
