#!/usr/bin/env bash
set -euo pipefail

# Reproducible SoulX Lite installation for the AutoDL RTX 4090D instance.
# All large files stay on the 50GB data disk.
SOULX_COMMIT=9bc03de06bb0de82cd6bc477804512ae06144bf2
DATA_ROOT=/root/autodl-tmp
ENV_ROOT="$DATA_ROOT/envs/flashhead"
SOURCE_ROOT="$DATA_ROOT/SoulX-FlashHead"
MODEL_ROOT="$DATA_ROOT/models"

source /etc/network_turbo >/dev/null 2>&1 || true
export HF_ENDPOINT=${HF_ENDPOINT:-https://hf-mirror.com}
export HF_HUB_DISABLE_XET=1
export PIP_CACHE_DIR="$DATA_ROOT/pip-cache"
export TMPDIR="$DATA_ROOT/tmp"
export CONDA_PKGS_DIRS="$DATA_ROOT/conda-pkgs"
mkdir -p "$TMPDIR" "$DATA_ROOT/envs" "$MODEL_ROOT"

if [ ! -d "$SOURCE_ROOT/.git" ]; then
  git clone https://github.com/Soul-AILab/SoulX-FlashHead.git "$SOURCE_ROOT"
fi
git -C "$SOURCE_ROOT" fetch origin "$SOULX_COMMIT"
git -C "$SOURCE_ROOT" checkout "$SOULX_COMMIT"

if [ ! -x "$ENV_ROOT/bin/python" ]; then
  /root/miniconda3/bin/conda create -y -p "$ENV_ROOT" python=3.10 pip
fi
"$ENV_ROOT/bin/python" -m pip install --upgrade pip setuptools wheel
"$ENV_ROOT/bin/python" -m pip install \
  torch==2.7.1 torchvision==0.22.1 \
  --index-url https://download.pytorch.org/whl/cu128
# The upstream file pins NCCL 2.27.3 while the official cu128 Torch wheel pins
# NCCL 2.26.2. It also lets xformers ask PyPI for a second CUDA build of the
# same Torch version. Both resolve to an impossible environment. Keep Torch's
# tested CUDA stack, install the xformers wheel without replacing it, and use
# the remaining official requirements unchanged.
grep -Ev '^(xformers|nvidia-nccl-cu12)' "$SOURCE_ROOT/requirements.txt" \
  > "$DATA_ROOT/soulx-requirements.filtered.txt"
"$ENV_ROOT/bin/python" -m pip install -r "$DATA_ROOT/soulx-requirements.filtered.txt"
"$ENV_ROOT/bin/python" -m pip install --no-deps xformers==0.0.31
"$ENV_ROOT/bin/python" -m pip install websockets==15.0.1 \
  'https://github.com/Dao-AILab/flash-attention/releases/download/v2.8.0.post2/flash_attn-2.8.0.post2%2Bcu12torch2.7cxx11abiFALSE-cp310-cp310-linux_x86_64.whl'

# The 6.1GB Lite checkpoint is mirrored byte-for-byte on ModelScope and is
# considerably faster from mainland AutoDL.  Keep the exact upstream SHA-256
# so a changing or truncated mirror can never be used silently.
SOULX_LITE="$MODEL_ROOT/SoulX/Model_Lite/diffusion_pytorch_model.safetensors"
SOULX_LITE_PART="$SOULX_LITE.partial"
SOULX_LITE_SHA=aaf1cde6e80ca23f740aae236c47954249f65b151db133cc0f77d3a138ccdf6e
mkdir -p "$(dirname "$SOULX_LITE")"
if [ ! -f "$SOULX_LITE" ]; then
  curl --fail --location --retry 10 --retry-all-errors --continue-at - \
    --output "$SOULX_LITE_PART" \
    'https://www.modelscope.cn/models/Soul-AILab/SoulX-FlashHead-1_3B/resolve/master/Model_Lite/diffusion_pytorch_model.safetensors'
  printf '%s  %s\n' "$SOULX_LITE_SHA" "$SOULX_LITE_PART" | sha256sum --check -
  mv "$SOULX_LITE_PART" "$SOULX_LITE"
fi

"$ENV_ROOT/bin/python" - <<'PY'
from huggingface_hub import snapshot_download

snapshot_download(
    "Soul-AILab/SoulX-FlashHead-1_3B",
    local_dir="/root/autodl-tmp/models/SoulX",
    allow_patterns=["Model_Lite/config.json", "VAE_LTX/*", "config.json", "model_index.json"],
)
snapshot_download(
    "facebook/wav2vec2-base-960h",
    local_dir="/root/autodl-tmp/models/wav2vec2-base-960h",
    allow_patterns=[
        "config.json",
        "preprocessor_config.json",
        "feature_extractor_config.json",
        "pytorch_model.bin",
    ],
)
PY

# Keep the original portrait sharp in the middle and fill the square canvas
# from a blurred copy. This preserves the actor's head and shoulders.
ffmpeg -y -ss 180.30 \
  -i /root/demo_backend/source_assets/真人原始录制.mp4 -frames:v 1 \
  -filter_complex \
  '[0:v]scale=512:512:force_original_aspect_ratio=increase,crop=512:512,boxblur=24:12[bg];[0:v]scale=-2:512[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,format=rgb24[v]' \
  -map '[v]' /root/demo_backend/processed/human-soulx-reference.png

"$ENV_ROOT/bin/python" - <<'PY'
import flash_attn
import torch
import transformers
import websockets

print(torch.__version__, torch.version.cuda, flash_attn.__version__, transformers.__version__, websockets.__version__)
assert torch.cuda.is_available()
PY
touch "$DATA_ROOT/soulx-setup.ready"
echo "SoulX setup complete"
