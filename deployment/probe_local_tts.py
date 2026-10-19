"""Measure local Qwen voice design before considering it for the live demo."""

import importlib.machinery
import sys
import time
import types

import soundfile as sf
import torch


# The VoiceDesign path does not invoke ONNX. The current isolated test
# environment omits this optional dependency until model quality is proven.
onnx = types.ModuleType('onnxruntime')
onnx.__spec__ = importlib.machinery.ModuleSpec('onnxruntime', None)
sys.modules['onnxruntime'] = onnx

from qwen_tts import Qwen3TTSModel


model_path = '/root/autodl-tmp/nurse-tts-model'
started = time.monotonic()
model = Qwen3TTSModel.from_pretrained(
    model_path,
    device_map='cuda:0',
    dtype=torch.bfloat16,
    attn_implementation='sdpa',
)
print('model_load_sec', round(time.monotonic() - started, 2), flush=True)

texts = [
    '哎，护士啊，我这脚麻得厉害，凉飕飕的，眼睛也看不清。你说这糖尿病，是不是要出大事了？',
    '唉，我最怕脚出了问题，还怕看不清东西。孩子们不在身边，我心里慌。',
]
instruct = '一位六十八岁的中国女性住院患者。声音中低、略带沙哑，语速稍慢，像在病房里与护士自然交谈；她有些焦虑和疲惫，但不夸张、不像播音员。'
for index, utterance in enumerate(texts):
    started = time.monotonic()
    wavs, sample_rate = model.generate_voice_design(
        text=utterance,
        language='Chinese',
        instruct=instruct,
    )
    elapsed = time.monotonic() - started
    path = f'/root/autodl-tmp/nurse-qwen-sample-{index}.wav'
    sf.write(path, wavs[0], sample_rate)
    print('generation', index, 'sec', round(elapsed, 2), 'audio_sec', round(len(wavs[0]) / sample_rate, 2), 'path', path, flush=True)
