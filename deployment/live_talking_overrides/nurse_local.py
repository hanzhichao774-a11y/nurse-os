"""Offline, low-latency Mandarin speech for the Wang Ayi demo."""

import os
import time
from threading import Lock

import numpy as np

from registry import register
from utils.logger import logger
from .base_tts import State
from .edge import EdgeTTS


_model = None
_model_lock = Lock()


def load_model():
    global _model
    with _model_lock:
        if _model is not None:
            return _model
        import sherpa_onnx

        directory = os.getenv('NURSE_TTS_MODEL_DIR', '/root/autodl-tmp/zh-ll-hf')
        config = sherpa_onnx.OfflineTtsConfig(
            model=sherpa_onnx.OfflineTtsModelConfig(
                vits=sherpa_onnx.OfflineTtsVitsModelConfig(
                    model=f'{directory}/model.onnx',
                    lexicon=f'{directory}/lexicon.txt',
                    tokens=f'{directory}/tokens.txt',
                ),
                num_threads=int(os.getenv('NURSE_TTS_THREADS', '8')),
            ),
            rule_fsts=f'{directory}/phone.fst,{directory}/date.fst,{directory}/number.fst',
        )
        if not config.validate():
            raise RuntimeError('离线中文语音模型文件不完整')
        started = time.monotonic()
        _model = sherpa_onnx.OfflineTts(config)
        logger.info('nurse local tts model loaded in %.3fs', time.monotonic() - started)
        return _model


@register('tts', 'nurselocal')
class NurseLocalTTS(EdgeTTS):
    def __init__(self, opt, parent):
        super().__init__(opt, parent)
        try:
            self.local_model = load_model()
        except Exception:
            self.local_model = None
            logger.exception('nurse local tts load failed; Edge fallback available')

    def txt_to_audio(self, msg: tuple[str, dict]):
        if self.local_model is None:
            return super().txt_to_audio(msg)
        text, textevent = msg
        started = time.monotonic()
        try:
            import sherpa_onnx

            generation = sherpa_onnx.GenerationConfig()
            generation.sid = int(os.getenv('NURSE_TTS_SPEAKER', '2'))
            generation.speed = float(os.getenv('NURSE_TTS_SPEED', '1.0'))
            audio = self.local_model.generate(text, generation)
            samples = np.asarray(audio.samples, dtype=np.float32)
            if audio.sample_rate != self.sample_rate:
                raise RuntimeError(f'Unexpected sample rate: {audio.sample_rate}')
            if len(samples) == 0:
                raise RuntimeError('Local TTS produced no audio')
            logger.info('nurse local tts first pcm ready in %.3fs; %.2fs audio',
                        time.monotonic() - started, len(samples) / self.sample_rate)
        except Exception:
            logger.exception('nurse local tts generation failed; using Edge')
            return super().txt_to_audio(msg)

        total = (len(samples) + self.chunk - 1) // self.chunk
        for index in range(total):
            if self.state != State.RUNNING:
                return
            frame = samples[index * self.chunk:(index + 1) * self.chunk]
            if len(frame) < self.chunk:
                frame = np.pad(frame, (0, self.chunk - len(frame)))
            event = {'text': text, **textevent}
            if index == 0:
                event['status'] = 'start'
            if index == total - 1 and index > 0:
                event['status'] = 'end'
            self.parent.put_audio_frame(frame, event)
        if total == 1:
            self.parent.put_audio_frame(np.zeros(self.chunk, dtype=np.float32),
                                        {'text': text, **textevent, 'status': 'end'})
