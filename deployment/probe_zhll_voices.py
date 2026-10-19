"""Generate five local voice samples for a human timbre check."""

import time

import sherpa_onnx
import soundfile as sf


root = '/root/autodl-tmp/zh-ll-hf'
config = sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=f'{root}/model.onnx',
            lexicon=f'{root}/lexicon.txt',
            tokens=f'{root}/tokens.txt',
        ),
        num_threads=8,
    ),
    rule_fsts=f'{root}/phone.fst,{root}/date.fst,{root}/number.fst',
)
assert config.validate()
tts = sherpa_onnx.OfflineTts(config)
text = '哎，护士啊，我这脚麻得厉害，眼睛也看不清。我心里慌得很。'
for sid in range(5):
    generation = sherpa_onnx.GenerationConfig()
    generation.sid = sid
    start = time.monotonic()
    audio = tts.generate(text, generation)
    path = f'/root/autodl-tmp/nurse-zhll-voice-{sid}.wav'
    sf.write(path, audio.samples, audio.sample_rate)
    print(sid, round(time.monotonic() - start, 3),
          round(len(audio.samples) / audio.sample_rate, 3), path, flush=True)
