"""Safari compatible HLS bridge for an on-demand LiveTalking session.

MediaMTX exposes H.264 + Opus. Safari can render the video variant but cannot
decode the Opus audio rendition in HLS, so FFmpeg copies H.264 and converts
only the audio to AAC in the same live playlist.
"""

from __future__ import annotations

import re
import subprocess
import threading
import time
from pathlib import Path


class MobileMedia:
    def __init__(self, root: Path, ffmpeg: str = "/usr/bin/ffmpeg") -> None:
        self.root = root
        self.ffmpeg = ffmpeg
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.processes: dict[str, tuple[subprocess.Popen[bytes], float]] = {}
        threading.Thread(target=self._reap, daemon=True, name="mobile-media-reaper").start()

    def start(self, session_id: str, avatar_id: str) -> Path:
        if not re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{4}", session_id):
            raise ValueError("Invalid session ID")
        if not re.fullmatch(r"[a-z0-9_]+", avatar_id):
            raise ValueError("Invalid avatar ID")
        directory = self.root / session_id
        with self.lock:
            existing = self.processes.get(session_id)
            if existing and existing[0].poll() is None:
                self.processes[session_id] = (existing[0], time.monotonic())
                return directory / "index.m3u8"
            if len([p for p, _ in self.processes.values() if p.poll() is None]) >= 4:
                raise RuntimeError("Too many concurrent mobile streams")
            directory.mkdir(parents=True, exist_ok=True)
            for old in directory.iterdir():
                if old.name in {"index.m3u8", "init.mp4"} or re.fullmatch(r"index\d+\.m4s", old.name):
                    old.unlink(missing_ok=True)
            command = [
                self.ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "fatal",
                "-rtsp_transport", "tcp", "-i",
                f"rtsp://127.0.0.1:8554/avatar/{session_id}?avatar={avatar_id}",
                "-map", "0:v:0", "-map", "0:a:0",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "96k", "-ac", "1",
                "-f", "hls", "-hls_time", "1", "-hls_list_size", "6",
                "-hls_flags", "delete_segments+independent_segments+omit_endlist",
                "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
                str(directory / "index.m3u8"),
            ]
            with (directory / "ffmpeg.log").open("ab") as log:
                process = subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=log, start_new_session=True,
                )
            self.processes[session_id] = (process, time.monotonic())
        return directory / "index.m3u8"

    def wait_ready(self, session_id: str, avatar_id: str, timeout: float = 15.0) -> Path:
        manifest = self.start(session_id, avatar_id)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if manifest.is_file() and manifest.stat().st_size > 50:
                self.touch(session_id)
                return manifest
            with self.lock:
                item = self.processes.get(session_id)
            if not item or item[0].poll() is not None:
                raise RuntimeError("Mobile media bridge exited before becoming ready")
            time.sleep(0.2)
        raise TimeoutError("Mobile media bridge did not become ready")

    def touch(self, session_id: str) -> None:
        with self.lock:
            item = self.processes.get(session_id)
            if item:
                self.processes[session_id] = (item[0], time.monotonic())

    def stop(self, session_id: str) -> None:
        with self.lock:
            item = self.processes.pop(session_id, None)
        if item and item[0].poll() is None:
            item[0].terminate()
            try:
                item[0].wait(timeout=2)
            except subprocess.TimeoutExpired:
                item[0].kill()

    def _reap(self) -> None:
        while True:
            time.sleep(10)
            now = time.monotonic()
            with self.lock:
                expired = [key for key, (proc, seen) in self.processes.items()
                           if proc.poll() is not None or now - seen > 60]
            for key in expired:
                self.stop(key)
