"""Download one public ModelScope model with ranged requests and SHA-256 checks."""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from urllib.parse import quote

import requests


MODEL = 'Qwen/Qwen3-TTS-12Hz-0.6B-Base'
DEST = Path('/root/autodl-tmp/qwen3-tts-base-06')
CHUNK = 16 * 1024 * 1024
WORKERS = 6
API = f'https://modelscope.cn/api/v1/models/{MODEL}/repo/files?Revision=master&Recursive=true'


def digest(path):
    hash_value = hashlib.sha256()
    with path.open('rb') as stream:
        for data in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            hash_value.update(data)
    return hash_value.hexdigest()


def download(entry):
    relative = entry['Path']
    size = entry['Size']
    expected = entry.get('Sha256') or ''
    target = DEST / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == size and (not expected or digest(target) == expected):
        print('skip', relative, flush=True)
        return

    url = f'https://modelscope.cn/models/{MODEL}/resolve/master/{quote(relative, safe="/")}'
    if size < CHUNK:
        response = requests.get(url, timeout=(15, 120))
        response.raise_for_status()
        if len(response.content) != size:
            raise RuntimeError(f'{relative}: expected {size} bytes, got {len(response.content)}')
        target.write_bytes(response.content)
    else:
        part = target.with_name(target.name + '.part')
        ledger = target.with_name(target.name + '.chunks.json')
        total = math.ceil(size / CHUNK)
        done = set(json.loads(ledger.read_text())) if ledger.exists() and part.exists() else set()
        descriptor = os.open(part, os.O_CREAT | os.O_RDWR, 0o644)
        os.ftruncate(descriptor, size)
        lock = threading.Lock()

        def fetch(index):
            start = index * CHUNK
            end = min(size, start + CHUNK) - 1
            for attempt in range(4):
                try:
                    response = requests.get(url, headers={'Range': f'bytes={start}-{end}'}, timeout=(15, 120))
                    response.raise_for_status()
                    if response.status_code != 206 or len(response.content) != end - start + 1:
                        raise RuntimeError(f'bad range response {response.status_code}: {len(response.content)}')
                    os.pwrite(descriptor, response.content, start)
                    with lock:
                        done.add(index)
                        ledger.write_text(json.dumps(sorted(done)))
                        if len(done) % 10 == 0 or len(done) == total:
                            print(relative, len(done), '/', total, flush=True)
                    return
                except Exception as exc:
                    if attempt == 3:
                        raise RuntimeError(f'{relative} chunk {index} failed: {exc}') from exc

        try:
            with ThreadPoolExecutor(max_workers=WORKERS) as pool:
                futures = [pool.submit(fetch, index) for index in range(total) if index not in done]
                for future in as_completed(futures):
                    future.result()
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if expected and digest(part) != expected:
            raise RuntimeError(f'{relative}: SHA-256 mismatch')
        part.rename(target)
        ledger.unlink(missing_ok=True)
    if expected and digest(target) != expected:
        raise RuntimeError(f'{relative}: SHA-256 mismatch')
    print('done', relative, size, flush=True)


files = requests.get(API, timeout=(15, 30)).json()['Data']['Files']
for item in files:
    if item.get('Type') == 'blob':
        download(item)
print('model_complete', flush=True)
