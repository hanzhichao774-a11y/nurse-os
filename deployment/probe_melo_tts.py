"""Measure an isolated, offline Mandarin TTS candidate before deployment."""

import os
import time

import sherpa_onnx
import soundfile as sf


root = os.environ.get('TTS_MODEL_DIR', '/root/autodl-tmp/melo-hf')
model_filename = os.environ.get('TTS_MODEL_FILENAME', 'model.int8.onnx')
speaker_id = int(os.environ.get('TTS_SPEAKER_ID', '0'))
config = sherpa_onnx.OfflineTtsConfig(
    model=sherpa_onnx.OfflineTtsModelConfig(
        vits=sherpa_onnx.OfflineTtsVitsModelConfig(
            model=f'{root}/{model_filename}',
            lexicon=f'{root}/lexicon.txt',
            tokens=f'{root}/tokens.txt',
        ),
        provider=os.environ.get('MELO_PROVIDER', 'cpu'),
        num_threads=int(os.environ.get('MELO_THREADS', '4')),
    ),
    rule_fsts=f'{root}/phone.fst,{root}/date.fst,{root}/number.fst',
)
assert config.validate()
started = time.monotonic()
tts = sherpa_onnx.OfflineTts(config)
print('load_sec', round(time.monotonic() - started, 3), flush=True)

for index, text in enumerate((
    '哎，护士啊，我这脚麻得厉害，凉飕飕的，眼睛也看不清。你说这糖尿病，是不是要出大事了？',
    '唉，我最怕脚出了问题，还怕看不清东西。孩子们不在身边，我心里慌。',
)):
    started = time.monotonic()
    generation = sherpa_onnx.GenerationConfig()
    generation.sid = speaker_id
    audio = tts.generate(text, generation)
    elapsed = time.monotonic() - started
    assert len(audio.samples) > 0
    out = f'/root/autodl-tmp/nurse-tts-sample-{speaker_id}-{index}.wav'
    sf.write(out, audio.samples, audio.sample_rate)
    print('generation', index, 'sec', round(elapsed, 3), 'audio_sec',
          round(len(audio.samples) / audio.sample_rate, 3), 'sample_rate',
          audio.sample_rate, 'path', out, flush=True)
