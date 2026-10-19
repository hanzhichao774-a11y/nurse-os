"""Generate a warm, consistent Chinese voice-over for the one-minute promo."""

from __future__ import annotations

import gc
import importlib.machinery
import json
from pathlib import Path
import sys
import types

import soundfile as sf
import torch


# VoiceDesign and Base cloning do not use ONNX in this workflow.  The small
# shim keeps qwen_tts importable in the purpose-built runtime used on AutoDL.
onnx = types.ModuleType("onnxruntime")
onnx.__spec__ = importlib.machinery.ModuleSpec("onnxruntime", None)
sys.modules.setdefault("onnxruntime", onnx)

from qwen_tts import Qwen3TTSModel  # noqa: E402


VOICE_DESIGN_MODEL = "/root/autodl-tmp/nurse-tts-model"
CLONE_MODEL = "/root/autodl-tmp/qwen3-tts-base-06"
OUTPUT_DIR = Path("/root/autodl-tmp/promo_voiceover")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

REFERENCE_TEXT = (
    "第一次走进病房，很多护生的大脑一片空白。"
    "请一位标准化病人，一小时要几百块。"
)
VOICE_INSTRUCTION = (
    "一位三十多岁的中国女性产品叙述者。声音温暖、清晰、可信，带真实呼吸和轻微停顿，"
    "像护理教师在镜头外真诚分享亲身观察。语速自然，重要词轻轻强调，克制而有感染力；"
    "不要广告腔，不要播音腔，不要夸张，不要逐字机械朗读。"
)

SEGMENTS = [
    {"id": "01", "start": 0.18, "end": 4.42, "text": "第一次走进病房，很多护生的大脑一片空白。"},
    {"id": "02", "start": 5.25, "end": 9.01, "text": "请一位标准化病人，一小时要几百块。"},
    {"id": "03", "start": 9.47, "end": 12.17, "text": "一次沟通实训，全年级排队。"},
    {"id": "04", "start": 13.74, "end": 19.18, "text": "所以，我们做了一位随叫随到、不会累的标准化病人——护语者。"},
    {"id": "05", "start": 20.43, "end": 23.87, "text": "她会讲病情，会焦虑，也会抗拒。"},
    {"id": "06", "start": 23.87, "end": 25.95, "text": "像一位真实的病人。"},
    {"id": "07", "start": 27.56, "end": 30.34, "text": "你说错了话，她会直接表现出来。"},
    {"id": "08", "start": 30.94, "end": 34.00, "text": "沟通的温度，在这里被真实放大。"},
    {"id": "09", "start": 35.43, "end": 38.01, "text": "网页、手机，随时开练。"},
    {"id": "10", "start": 39.43, "end": 43.95, "text": "每一轮对话结束，AI教师都会从五个维度打分。"},
    {"id": "11", "start": 44.45, "end": 47.17, "text": "告诉你下一次，怎样做得更好。"},
    {"id": "12", "start": 48.65, "end": 51.11, "text": "现在，她已经在两个班级试点。"},
    {"id": "13", "start": 51.11, "end": 54.29, "text": "六十多名同学，练了两百多轮。"},
    {"id": "14", "start": 55.62, "end": 59.48, "text": "护语者，让每一位护生，练够了，再上岗。"},
]


def write_wave(path: Path, waveform, sample_rate: int) -> float:
    samples = waveform.reshape(-1)
    sf.write(path, samples, sample_rate, subtype="PCM_16")
    return len(samples) / sample_rate


torch.manual_seed(20260922)
designer = Qwen3TTSModel.from_pretrained(
    VOICE_DESIGN_MODEL,
    device_map="cuda:0",
    dtype=torch.bfloat16,
    attn_implementation="sdpa",
)
with torch.inference_mode():
    reference_wavs, reference_rate = designer.generate_voice_design(
        text=REFERENCE_TEXT,
        language="Chinese",
        instruct=VOICE_INSTRUCTION,
    )
reference_path = OUTPUT_DIR / "reference.wav"
reference_duration = write_wave(reference_path, reference_wavs[0], int(reference_rate))
print("reference", round(reference_duration, 3), flush=True)

del reference_wavs, designer
gc.collect()
torch.cuda.empty_cache()

cloner = Qwen3TTSModel.from_pretrained(
    CLONE_MODEL,
    device_map="cuda:0",
    dtype=torch.bfloat16,
    attn_implementation="sdpa",
)
prompt = cloner.create_voice_clone_prompt(
    ref_audio=str(reference_path),
    ref_text=REFERENCE_TEXT,
    x_vector_only_mode=False,
)

manifest = {
    "voice_instruction": VOICE_INSTRUCTION,
    "reference_text": REFERENCE_TEXT,
    "reference_duration": round(reference_duration, 3),
    "segments": [],
}
for item in SEGMENTS:
    torch.manual_seed(20260922 + int(item["id"]))
    with torch.inference_mode():
        waveforms, sample_rate = cloner.generate_voice_clone(
            text=item["text"],
            language="Chinese",
            voice_clone_prompt=prompt,
            non_streaming_mode=True,
        )
    path = OUTPUT_DIR / f"segment_{item['id']}.wav"
    duration = write_wave(path, waveforms[0], int(sample_rate))
    entry = dict(item)
    entry.update(
        target_duration=round(item["end"] - item["start"], 3),
        generated_duration=round(duration, 3),
        path=str(path),
    )
    manifest["segments"].append(entry)
    print(item["id"], round(duration, 3), item["text"], flush=True)

(OUTPUT_DIR / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
print("complete", len(SEGMENTS), flush=True)
