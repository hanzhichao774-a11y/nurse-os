"""Replace only narration in the extended promo and preserve demo audio."""

from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
VIDEO = Path(
    "/Users/zhichao.han/Library/Containers/com.tencent.xinWeChat/Data/Documents/"
    "xwechat_files/lyremins_b82f/msg/video/2026-09/32af974b0b1ae9032c530237c097ee53_raw.mp4"
)
VOICE_DIR = ROOT / "artifacts" / "promo_voiceover"
ORIGINAL_AUDIO = ROOT / "artifacts" / "promo_v2_original_audio_synced.wav"
MUSIC = (
    ROOT / "artifacts" / "promo_v2_synced_stems" / "htdemucs"
    / "promo_v2_original_audio_synced" / "no_vocals.wav"
)
NARRATION = ROOT / "artifacts" / "护语者宣传片V2-自然旁白.wav"
MIX = ROOT / "artifacts" / "护语者宣传片V2-优化混音.wav"
OUTPUT = ROOT / "artifacts" / "护语者宣传片V2-自然旁白版.mp4"

# The original web demo audio begins slightly before its first matching visual
# cut.  This interval is decoded and encoded unchanged, with no voice removal,
# gain, compression, or replacement.
DEMO_START = 20.03
DEMO_END = 48.15
END = 75.72

# Generated voice clips already used in the first promo revision.  Their
# leading silence is trimmed while retaining 80 ms of breath room.  Delays are
# chosen so audible speech matches the detected starts in this source video.
STARTS = {
    "01": 0.543,
    "02": 5.047,
    "03": 9.223,
    "04": 14.099,
    "09": 49.079,
    "10": 55.000,
    "11": 59.931,
    "12": 63.400,
    "13": 66.800,
    "14": 71.650,
}


inputs: list[str] = []
filters: list[str] = []
labels: list[str] = []
for index, (segment_id, start) in enumerate(STARTS.items()):
    inputs += ["-i", str(VOICE_DIR / f"segment_{segment_id}.wav")]
    label = f"v{index}"
    filters.append(
        f"[{index}:a]aresample=48000,"
        "silenceremove=start_periods=1:start_silence=0.08:start_threshold=-48dB,"
        f"asetpts=N/SR/TB,highpass=f=65,adelay={round(start * 1000)}:all=1[{label}]"
    )
    labels.append(f"[{label}]")
filters.append(
    "".join(labels)
    + f"amix=inputs={len(labels)}:duration=longest:normalize=0:dropout_transition=0,"
      "loudnorm=I=-16:TP=-1.5:LRA=7[narration]"
)
subprocess.run(
    [
        "ffmpeg", "-y", *inputs,
        "-filter_complex", ";".join(filters),
        "-map", "[narration]", "-ar", "48000", "-ac", "2", str(NARRATION),
    ],
    check=True,
)

# Compose three sequential regions.  Only the middle region uses the original
# mixed track, so patient dialogue and all browser/demo sounds stay intact.
filter_complex = (
    f"[0:a]atrim=start=0:end={DEMO_START},asetpts=PTS-STARTPTS[bed_a];"
    f"[1:a]atrim=start=0:end={DEMO_START},asetpts=PTS-STARTPTS[narr_a];"
    "[bed_a][narr_a]amix=inputs=2:duration=first:normalize=0,"
    "alimiter=limit=0.891:attack=5:release=80[a];"
    f"[2:a]atrim=start={DEMO_START}:end={DEMO_END},asetpts=PTS-STARTPTS[b];"
    f"[0:a]atrim=start={DEMO_END}:end={END},asetpts=PTS-STARTPTS[bed_c];"
    f"[1:a]atrim=start={DEMO_END}:end={END},asetpts=PTS-STARTPTS[narr_c];"
    "[bed_c][narr_c]amix=inputs=2:duration=first:normalize=0,"
    "alimiter=limit=0.891:attack=5:release=80[c];"
    "[a][b][c]concat=n=3:v=0:a=1[mix]"
)
subprocess.run(
    [
        "ffmpeg", "-y", "-i", str(MUSIC), "-i", str(NARRATION),
        "-i", str(ORIGINAL_AUDIO), "-filter_complex", filter_complex,
        "-map", "[mix]", "-ar", "48000", "-ac", "2", str(MIX),
    ],
    check=True,
)

subprocess.run(
    [
        "ffmpeg", "-y", "-i", str(VIDEO), "-i", str(MIX),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-t", str(END), "-movflags", "+faststart", str(OUTPUT),
    ],
    check=True,
)

print(OUTPUT)
