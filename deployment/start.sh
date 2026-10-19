#!/usr/bin/env bash
set -e

nginx -t
if ! pgrep -x nginx >/dev/null; then
  nginx
fi

if ! pgrep -x mediamtx >/dev/null; then
  cd /root/mediamtx
  ./mediamtx > /root/mediamtx/demo-mediamtx.log 2>&1 &
fi

source /root/miniconda3/etc/profile.d/conda.sh
conda activate livetalking

if ! curl --silent --fail http://127.0.0.1:8000/health >/dev/null; then
  cd /root/demo_backend
  python -m uvicorn app:app --app-dir /root/demo_backend --host 127.0.0.1 --port 8000 > /root/demo_backend/demo.log 2>&1 &
fi

# SoulX is optional at boot: the demo selects LiveTalking automatically until
# the renderer finishes loading. Its environment and checkpoints live on the
# data disk so a large PyTorch install cannot fill the AutoDL system disk.
if [ -f /root/autodl-tmp/soulx-setup.ready ] && \
   ! pgrep -f 'soulx_server.py.*human-soulx-reference.png' >/dev/null; then
  cd /root/autodl-tmp/SoulX-FlashHead
  PYTHONPATH=/root/demo_backend nohup /root/autodl-tmp/envs/flashhead/bin/python \
    /root/demo_backend/soulx_server.py \
    --cond-image /root/demo_backend/processed/human-soulx-reference.png \
    --ckpt /root/autodl-tmp/models/SoulX \
    --wav2vec /root/autodl-tmp/models/wav2vec2-base-960h \
    --port 8791 \
    > /root/demo_backend/soulx.log 2>&1 &
fi

if [ -f /root/autodl-tmp/soulx-setup.ready ] && \
   ! pgrep -f 'soulx_server.py.*wang-ayi-soulx-reference.png' >/dev/null; then
  cd /root/autodl-tmp/SoulX-FlashHead
  PYTHONPATH=/root/demo_backend nohup /root/autodl-tmp/envs/flashhead/bin/python \
    /root/demo_backend/soulx_server.py \
    --cond-image /root/demo_backend/processed/wang-ayi-soulx-reference.png \
    --ckpt /root/autodl-tmp/models/SoulX \
    --wav2vec /root/autodl-tmp/models/wav2vec2-base-960h \
    --port 8792 \
    > /root/demo_backend/soulx-wang-ayi.log 2>&1 &
fi

for ((attempt=0; attempt<60; attempt++)); do
  if curl --silent --fail http://127.0.0.1:8000/health >/dev/null; then
    break
  fi
  sleep 0.5
done
if ! curl --silent --fail http://127.0.0.1:8000/health >/dev/null; then
  echo "Demo 后端启动失败，请查看 /root/demo_backend/demo.log" >&2
  exit 1
fi

if ! curl --silent --fail http://127.0.0.1:8010/index-whep.html >/dev/null; then
  cd /root/LiveTalking
  exec python app.py --transport webrtc --model wav2lip --avatar_id wang_ayi --batch_size 8 --tts nurselocal
fi
