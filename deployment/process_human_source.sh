#!/usr/bin/env bash
set -euo pipefail

input=${1:?用法: process_human_source.sh 输入视频 [输出目录]}
output_dir=${2:-artifacts/source-review}
ffmpeg_bin=${FFMPEG_BIN:-ffmpeg}

mkdir -p "$output_dir"

# 180.30s 附近是原片中最长且正脸、闭嘴、动作轻微的安静片段。
"$ffmpeg_bin" -y -ss 180.30 -i "$input" -t 1.00 -an \
  -r 25 -c:v libx264 -pix_fmt yuv420p \
  "$output_dir/human-idle-snippet.mp4"

# 将竖屏人物完整保留在 16:9 画布中央，背景由原画面模糊填充。
"$ffmpeg_bin" -y -stream_loop 7 -i "$output_dir/human-idle-snippet.mp4" -t 8 \
  -filter_complex \
  '[0:v]scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720,boxblur=24:12[bg];[0:v]scale=-2:720[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]' \
  -map '[v]' -an -r 25 -c:v libx264 -preset medium -crf 20 \
  "$output_dir/human-avatar-base.mp4"

"$ffmpeg_bin" -y -i "$output_dir/human-avatar-base.mp4" -frames:v 1 \
  "$output_dir/human-poster.jpg"

# 保留真人音色，去除低频环境声和高频噪声，并规范响度供后续声音模型使用。
"$ffmpeg_bin" -y -ss 182.50 -i "$input" -t 8.00 -vn -ac 1 -ar 16000 \
  -af 'highpass=f=80,lowpass=f=7600,afftdn=nf=-25,loudnorm=I=-20:LRA=7:TP=-1.5' \
  -c:a pcm_s16le "$output_dir/human-reference-8s.wav"

"$ffmpeg_bin" -y -i "$input" -vn -ac 1 -ar 16000 \
  -af 'highpass=f=80,lowpass=f=7600,afftdn=nf=-25,loudnorm=I=-20:LRA=7:TP=-1.5' \
  -c:a pcm_s16le "$output_dir/cleaned-voice.wav"

