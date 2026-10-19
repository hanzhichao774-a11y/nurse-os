"""Standalone SoulX quality probe for the consented young male patient.

Records three clips from the renderer itself:
  1. eight seconds of silence/idle motion;
  2. the cached short greeting;
  3. at least thirty seconds assembled from the cloned fallback lines.

The output contains MP4 clips and machine-readable frame/timing evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import hashlib
import json
import subprocess
import time
import wave
from dataclasses import asdict, dataclass
from pathlib import Path

from avatar_provider import TARGET_SAMPLE_RATE, wav_to_pcm16


RENDERER_AUDIO_CHUNK_SAMPLES = round(TARGET_SAMPLE_RATE * 0.16)


@dataclass
class Result:
    name: str
    duration_seconds: float
    audio_seconds: float
    frames: int
    observed_fps: float
    unique_frame_ratio: float
    first_frame_seconds: float | None
    output: str


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(TARGET_SAMPLE_RATE)
        target.writeframes(pcm)


def long_audio(directory: Path, seconds: float = 30.0) -> bytes:
    files = sorted(directory.glob("*.wav"))
    if not files:
        raise FileNotFoundError(f"no fallback WAV files in {directory}")
    silence = b"\0\0" * int(TARGET_SAMPLE_RATE * 0.18)
    output = bytearray()
    index = 0
    while len(output) / 2 / TARGET_SAMPLE_RATE < seconds:
        output.extend(wav_to_pcm16(files[index % len(files)].read_bytes()))
        output.extend(silence)
        index += 1
    return bytes(output)


async def pace_audio(ws, pcm: bytes) -> None:
    """Feed SoulX on the same wall clock used by browser audio playback."""

    chunk_bytes = RENDERER_AUDIO_CHUNK_SAMPLES * 2
    started = time.perf_counter()
    for index, begin in enumerate(range(0, len(pcm), chunk_bytes)):
        await ws.send(json.dumps({
            "type": "audio",
            "pcm": base64.b64encode(pcm[begin:begin + chunk_bytes]).decode("ascii"),
        }))
        deadline = started + (index + 1) * RENDERER_AUDIO_CHUNK_SAMPLES / TARGET_SAMPLE_RATE
        delay = deadline - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)


async def record(
    renderer_url: str,
    output_root: Path,
    name: str,
    duration: float,
    pcm: bytes | None,
    audio_lead_ms: int,
) -> Result:
    import websockets

    directory = output_root / name
    directory.mkdir(parents=True, exist_ok=True)
    for old in directory.glob("*.jpg"):
        old.unlink()
    frames: list[bytes] = []
    timestamps: list[float] = []
    async with websockets.connect(renderer_url, max_size=16 * 1024 * 1024) as ws:
        ready = json.loads(await ws.recv())
        if ready.get("type") != "ready":
            raise RuntimeError(f"unexpected renderer greeting: {ready}")
        await ws.send(json.dumps({"type": "flush"}))
        while True:
            event = await ws.recv()
            if isinstance(event, str) and json.loads(event).get("type") == "flushed":
                break
        started = time.perf_counter()
        sender = asyncio.create_task(pace_audio(ws, pcm)) if pcm else None
        deadline = started + duration
        while time.perf_counter() < deadline:
            remaining = deadline - time.perf_counter()
            try:
                message = await asyncio.wait_for(ws.recv(), timeout=max(0.05, remaining))
            except (TimeoutError, asyncio.TimeoutError):
                break
            if isinstance(message, bytes):
                frames.append(message)
                timestamps.append(time.perf_counter() - started)
        if sender:
            await sender
    for index, frame in enumerate(frames):
        (directory / f"{index:06d}.jpg").write_bytes(frame)
    audio_seconds = len(pcm or b"") / 2 / TARGET_SAMPLE_RATE
    if pcm:
        write_wav(directory / "audio.wav", pcm)
    hashes = {hashlib.sha256(frame).digest() for frame in frames}
    output = output_root / f"{name}.mp4"
    command = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-framerate", "25", "-i", str(directory / "%06d.jpg"),
    ]
    if pcm:
        command += [
            "-i", str(directory / "audio.wav"),
            "-filter_complex", f"[1:a]adelay={audio_lead_ms}:all=1[a]",
            "-map", "0:v:0", "-map", "[a]",
        ]
    command += [
        "-t", f"{duration:.3f}", "-c:v", "libx264", "-preset", "medium",
        "-crf", "18", "-pix_fmt", "yuv420p",
    ]
    if pcm:
        command += ["-c:a", "aac", "-b:a", "128k"]
    command.append(str(output))
    subprocess.run(command, check=True)
    return Result(
        name=name,
        duration_seconds=duration,
        audio_seconds=round(audio_seconds, 3),
        frames=len(frames),
        observed_fps=round(len(frames) / duration, 3),
        unique_frame_ratio=round(len(hashes) / max(1, len(frames)), 4),
        first_frame_seconds=round(timestamps[0], 3) if timestamps else None,
        output=str(output),
    )


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--renderer", default="ws://127.0.0.1:8791")
    parser.add_argument("--audio-root", type=Path, default=Path("/root/demo_backend/assets/fallback_audio/human_candidate"))
    parser.add_argument("--output", type=Path, default=Path("/root/demo_backend/qa/soulx-quality"))
    parser.add_argument("--lead-ms", type=int, default=1300)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    greeting = wav_to_pcm16((args.audio_root / "greeting.wav").read_bytes())
    long_pcm = long_audio(args.audio_root)
    scenarios = [
        ("idle-8s", 8.0, None),
        ("short-reply", len(greeting) / 2 / TARGET_SAMPLE_RATE + 3.0, greeting),
        ("long-reply-30s", len(long_pcm) / 2 / TARGET_SAMPLE_RATE + 3.0, long_pcm),
    ]
    results = []
    for name, duration, pcm in scenarios:
        results.append(await record(args.renderer, args.output, name, duration, pcm, args.lead_ms))
    report = {
        "renderer": args.renderer,
        "audio_lead_ms": args.lead_ms,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "results": [asdict(item) for item in results],
    }
    (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
