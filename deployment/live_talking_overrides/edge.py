"""Stream Edge TTS into LiveTalking's 20 ms audio frames."""

import asyncio
import time

import av
import edge_tts
import numpy as np

from utils.logger import logger
from .base_tts import BaseTTS, State
from registry import register


@register("tts", "edgetts")
class EdgeTTS(BaseTTS):
    def txt_to_audio(self, msg: tuple[str, dict]):
        text, textevent = msg
        voice = self.opt.REF_FILE or "zh-CN-YunxiaNeural"
        voicename = textevent.get('tts', {}).get('ref_file', voice)
        started_at = time.time()
        for attempt in range(3):
            self._stream_emitted = 0
            try:
                asyncio.run(self._stream_audio(voicename, text, textevent, started_at))
                if self._stream_emitted:
                    break
                raise RuntimeError('No audio was received')
            except Exception as exc:
                logger.warning(f'edgetts attempt {attempt + 1}/3 failed: {type(exc).__name__} status={getattr(exc, "status", "")}', exc_info=True)
                if self.state != State.RUNNING:
                    return
                if self._stream_emitted:
                    self.parent.put_audio_frame(np.zeros(self.chunk, dtype=np.float32), {'text': text, **textevent, 'status': 'end'})
                    break
                if attempt < 2 and self.state == State.RUNNING:
                    time.sleep(0.2 * (attempt + 1))
        else:
            self.parent.put_audio_frame(np.zeros(self.chunk, dtype=np.float32), {'text': text, **textevent, 'status': 'error'})
        logger.info(f'-------edge tts stream time:{time.time()-started_at:.4f}s')

    async def _stream_audio(self, voicename: str, text: str, textevent: dict, started_at: float):
        decoder = av.CodecContext.create('mp3', 'r')
        resampler = av.AudioResampler(format='s16', layout='mono', rate=self.sample_rate)
        pcm = bytearray()
        held = None
        emitted = 0

        def emit(frame, status=None):
            nonlocal emitted
            if self.state != State.RUNNING:
                return
            eventpoint = {'text': text, **textevent}
            if status:
                eventpoint['status'] = status
            self.parent.put_audio_frame(frame, eventpoint)
            emitted += 1
            self._stream_emitted += 1
            if emitted == 1:
                logger.info(f'-------edge tts first pcm:{time.time()-started_at:.4f}s')

        def feed(decoded):
            nonlocal held
            for output in resampler.resample(decoded):
                pcm.extend(output.to_ndarray().tobytes())
                while len(pcm) >= self.chunk * 2:
                    data = bytes(pcm[:self.chunk * 2])
                    del pcm[:self.chunk * 2]
                    frame = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0
                    if held is not None:
                        emit(held, 'start' if emitted == 0 else None)
                    held = frame

        if self.opt.avatar_id == 'wang_ayi':
            communicate = edge_tts.Communicate(text, voicename, rate='-5%', pitch='-8Hz')
        else:
            communicate = edge_tts.Communicate(text, voicename)
        async for chunk in communicate.stream():
            if self.state != State.RUNNING:
                break
            if chunk['type'] == 'audio':
                for packet in decoder.parse(chunk['data']):
                    for frame in decoder.decode(packet):
                        feed(frame)
        if self.state != State.RUNNING:
            return
        for packet in decoder.parse(b''):
            for frame in decoder.decode(packet):
                feed(frame)
        for frame in decoder.decode(None):
            feed(frame)
        for output in resampler.resample(None):
            pcm.extend(output.to_ndarray().tobytes())
        while len(pcm) >= self.chunk * 2:
            data = bytes(pcm[:self.chunk * 2])
            del pcm[:self.chunk * 2]
            frame = np.frombuffer(data, dtype='<i2').astype(np.float32) / 32768.0
            if held is not None:
                emit(held, 'start' if emitted == 0 else None)
            held = frame
        if held is not None:
            emit(held, 'end' if emitted else 'start')
            if emitted == 1:
                emit(np.zeros(self.chunk, dtype=np.float32), 'end')
