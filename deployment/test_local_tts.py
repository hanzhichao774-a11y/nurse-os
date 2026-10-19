"""Exercise the actual local model to LiveTalking PCM frame boundary."""

from collections import Counter
from types import SimpleNamespace
import time

from tts.nurse_local import NurseLocalTTS


class Parent:
    def __init__(self):
        self.frames = []

    def put_audio_frame(self, frame, event):
        self.frames.append((frame, event))


parent = Parent()
tts = NurseLocalTTS(SimpleNamespace(fps=25, REF_FILE='', avatar_id='wang_ayi'), parent)
assert tts.local_model is not None
started = time.monotonic()
tts.txt_to_audio(('哎，我这脚麻得厉害，最近看东西也模糊。', {}))
elapsed = time.monotonic() - started
statuses = Counter(event.get('status') for _, event in parent.frames)
assert statuses['start'] == statuses['end'] == 1
assert len(parent.frames) > 100
assert all(len(frame) == 320 for frame, _ in parent.frames)
print('generation_sec', round(elapsed, 3), 'audio_frames', len(parent.frames),
      'statuses', dict(statuses), flush=True)
