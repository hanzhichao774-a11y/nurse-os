"""Generate Wang Ayi's reviewed, cloned-voice response bank."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import requests


ROOT = Path("/root/demo_backend")
sys.path.insert(0, str(ROOT))
from case_fallback import WANG_AYI_RESPONSE_BANK  # noqa: E402


destination = ROOT / "assets" / "fallback_audio" / "wang_ayi"
destination.mkdir(parents=True, exist_ok=True)
items = [
    ("greeting", "哎……护士来了啊。"),
    *[(response_id, response[0]) for response_id, response in WANG_AYI_RESPONSE_BANK.items()],
]
missing = [(response_id, text) for response_id, text in items if not (destination / f"{response_id}.wav").is_file()]

for offset in range(0, len(missing), 6):
    batch = missing[offset:offset + 6]
    response = requests.post(
        "http://127.0.0.1:8090/tts-batch",
        json={"texts": [text for _, text in batch]},
        timeout=240,
    )
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        for index, (response_id, _) in enumerate(batch):
            target = destination / f"{response_id}.wav"
            target.write_bytes(archive.read(f"{index}.wav"))
            print(response_id, target.stat().st_size, flush=True)

manifest = {
    response_id: {
        "text": text,
        "sha256": hashlib.sha256((destination / f"{response_id}.wav").read_bytes()).hexdigest(),
    }
    for response_id, text in items
}
(destination / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
)
print("generated", len(missing), "new files;", len(items), "total", flush=True)
