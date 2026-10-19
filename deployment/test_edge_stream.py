from collections import Counter
from types import SimpleNamespace
import time

from tts.edge import EdgeTTS


class Parent:
    def __init__(self):
        self.frames = []

    def put_audio_frame(self, frame, event):
        self.frames.append((frame, event, time.monotonic()))


parent = Parent()
opt = SimpleNamespace(fps=25, REF_FILE='', avatar_id='wang_ayi')
tts = EdgeTTS(opt, parent)
start = time.monotonic()
tts.txt_to_audio(('哎，我这脚麻了一个月了，最近看东西也模糊。', {'tts': {'ref_file': 'zh-CN-XiaoyiNeural'}}))
statuses = Counter(event.get('status') for _, event, _ in parent.frames)
print('first_frame_sec', round(parent.frames[0][2] - start, 3))
print('frames', len(parent.frames), 'statuses', dict(statuses))
assert len(parent.frames) >= 40
assert statuses['start'] == 1
assert statuses['end'] == 1
assert all(len(frame) == 320 for frame, _, _ in parent.frames)


class TemporaryError(Exception):
    status = 503


retry_parent = Parent()
retry_tts = EdgeTTS(opt, retry_parent)
attempts = 0


async def transient_failure(*_):
    global attempts
    attempts += 1
    if attempts < 3:
        raise TemporaryError()
    retry_tts._stream_emitted = 1


retry_tts._stream_audio = transient_failure
retry_tts.txt_to_audio(('重试测试', {}))
assert attempts == 3


failure_parent = Parent()
failure_tts = EdgeTTS(opt, failure_parent)


async def permanent_failure(*_):
    raise TemporaryError()


failure_tts._stream_audio = permanent_failure
failure_tts.txt_to_audio(('失败测试', {}))
assert failure_parent.frames[-1][1]['status'] == 'error'
print('retry_and_error_event_ok')
