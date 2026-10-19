"""Measure first audible speech after the recorded send event."""

import json
from pathlib import Path
import re
import subprocess
import sys


recording = Path(sys.argv[1])
metrics_file = Path(sys.argv[2])
limit = float(sys.argv[3]) if len(sys.argv) > 3 else 6.0
ffmpeg = '/tmp/nurse-ffmpeg/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1'
result = subprocess.run(
    [ffmpeg, '-i', str(recording), '-af', 'silencedetect=noise=-38dB:d=0.1', '-f', 'null', '-'],
    capture_output=True, text=True, check=True,
)
matches = re.findall(r'silence_end: ([0-9.]+)', result.stderr)
if not matches:
    raise RuntimeError('未从音轨检测到患者语音')
metrics = json.loads(metrics_file.read_text())
onset = float(matches[0])
metrics['audibleOnsetSeconds'] = round(onset, 3)
metrics['sendToAudibleSeconds'] = round(onset - metrics['sendOffsetSeconds'], 3)
metrics['audibleDetection'] = 'ffmpeg silencedetect: -38 dB, minimum 0.1 s'
if metrics['sendToAudibleSeconds'] <= 0 or metrics['sendToAudibleSeconds'] > limit:
    raise AssertionError(f"患者实际出声不满足 {limit:.1f} 秒目标")
metrics_file.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(metrics, ensure_ascii=False, indent=2))
