# 护语者 V1 Demo

面向护理专业学生的护患沟通实训演示：多病例选择、实时数字人对话、五维评分报告。数字人只扮演患者，不提供诊断或用药建议。

## 服务器目录

- 前端：`/root/LiveTalking/web/demo/`
- 后端：`/root/demo_backend/`
- 会话：`/root/demo_backend/data/sessions/{session_id}.json`
- 病例：`/root/demo_backend/data/cases/*.json`
- 原文 Prompt：`/root/demo_backend/prompts/`
- nginx 配置备份：`/root/demo_backend/backup/nginx-default-before-demo.conf`
- 音画修复前备份：`/root/demo_backend/backup/av-repair-20260920/`
- 启动脚本：`/root/start.sh`

## 环境变量

在 `/root/demo_backend/.env` 配置 `LLM_BASE_URL`、`LLM_MODEL`、`LLM_API_KEY`、`LIVETALKING_BASE_URL`、`AVATAR_TTS_PROVIDER=nurselocal`。参见 `.env.example`。服务会在每次请求时重读 `.env`，换密钥无需重启。真实密钥不要提交到代码库。

目前服务器配置为 DeepSeek OpenAI 兼容接口和 `deepseek-flash`。用户提供的 `deepseek-v4` 模型名经实际请求返回 400；[DeepSeek 官方模型列表](https://api-docs.deepseek.com/quick_start/pricing/)列出的当前模型名是 `deepseek-flash` 和 `deepseek-v4-pro`。选用 flash 以缩短演示等待时间，并显式关闭思考模式。可按需切到 `deepseek-v4-pro`，但应重新验收延迟。

## 安装与启动

```bash
source /root/miniconda3/etc/profile.d/conda.sh
conda activate livetalking
pip install -r /root/demo_backend/requirements.txt
nginx -t && nginx -s reload
bash /root/start.sh
```

`/root/start.sh` 会启动 nginx、mediamtx、Demo 后端、两套 SoulX renderer 和 LiveTalking 回退服务。后端健康检查：`curl http://127.0.0.1:8000/health`。声纹模型只在重新生成固定语音库时临时启动，演示运行时不占用显存。SoulX 首次部署执行 `bash /root/demo_backend/setup_soulx.sh`，环境、源码和权重均写入 `/root/autodl-tmp`。

本地通过 SSH 隧道打开演示，不需要公网端口或域名：

```bash
ssh -N -L 6006:localhost:6006 -L 6008:localhost:6008 -p <SSH端口> root@<服务器地址>
```

Chrome 打开 `http://localhost:6006/demo/`，或在 AutoDL 控制台复制 6006 的 HTTPS 公网映射地址并加 `/demo/`。不带尾部斜杠的 `/demo` 由 nginx 相对重定向，部署修复脚本为 `deployment/fix_public_demo_redirect.py`。本机隧道使用 6008 ICE-TCP 播放 WebRTC；公网 AutoDL HTTPS 代理无法承载原始 ICE TCP，因此浏览器改走同源 HLS。`mobile_media.py` 按需启动 FFmpeg，将 MediaMTX 的 H.264/Opus 转为 H.264/AAC 并生成同一条音视频播放列表；Safari 原生播放，Chrome 使用项目内置的 hls.js 1.7.3。停止实训或页面关闭会停止转码，失去媒体请求 60 秒后也会自动回收。服务器需安装 `ffmpeg`。8000 只监听服务器本机，nginx 把 `/api/demo/` 转发到后端。说话状态同时订阅 LiveTalking `/sse` 事件并轮询 `/is_speaking`，nginx 对 SSE 关闭缓冲并保持长连接。语音输入需要浏览器麦克风权限，无法使用时可打字并按 Enter。

每轮对话使用各病例的 System Prompt 和完整对话历史调用 DeepSeek，从该病例的 50 条审核回答中选择一个编号。模型不能改写句子。王阿姨和林先生分别使用 `127.0.0.1:8792`、`127.0.0.1:8791` 的 SoulX-FlashHead Lite renderer；上传视频仅用于提取人物参考帧和声音。SoulX 通过同源 WebSocket 连续输出 512×512、25 FPS JPEG 帧，静音时仍生成呼吸与眨眼，不播放预录视频循环。同一份 16 kHz PCM 同时驱动画面和浏览器 WebAudio；浏览器确认 AudioContext 已运行并完成音频排程后，服务端再按 160 ms 分片、真实时钟节奏向 SoulX 喂入音频，声音提前 1.3 秒对齐渲染缓存。

王阿姨和林先生的“开场白 + 50 条回答”部署后分别保存在 `assets/fallback_audio/wang_ayi/` 和 `assets/fallback_audio/human_candidate/`。每个目录都有文本与音频 SHA-256 清单。公开仓库不包含授权语音文件，部署时需单独恢复。实际展示和播报采用同一条审核整句，避免现场声纹合成造成 10 秒以上等待。评分仍优先调用评分 Prompt；超时后用本场学生原话生成带轮次依据的报告。

两个可用病例的 `avatar_provider` 都是 `soulx`，后端根据 `case_id` 选择对应 renderer。开始会话时若该病例的 SoulX 尚未就绪，后端会把该场会话固定回退到 LiveTalking，避免演示入口不可用。浏览器通过 `/api/demo/avatar/ws/{session_id}` 接收 SoulX 帧与音频；点击打断会同时清空浏览器音频、服务端语音队列和 SoulX 渲染队列。

`deployment/soulx_server.py` 参考 [VoxEMW](https://github.com/emwstudio/VoxEMW) 的 SoulX Lite 分段生成与节奏控制实现，并针对本 Demo 增加 flush 代际检查、立即闭口参考帧、浏览器音频就绪握手和会话级队列清理。采用的 VoxEMW 版本为提交 `63560df1512d4778dce86e975954bff5899de692`；MIT 许可副本见 `VoxEMW-LICENSE`。SoulX 上游固定为提交 `9bc03de`，模型权重校验值记录在 `setup_soulx.sh`。

当前 LiveTalking 增量修改保存在本地 `deployment/live_talking_overrides/`：两位患者的底板只向前循环，静音帧使用安静口型。播放器用同一个 `<video>` 播放音画。重新部署 LiveTalking 源码时须同步覆盖 `app.py`、`avatars/base_avatar.py`、`avatars/wav2lip_avatar.py`、`tts/edge.py`、`tts/nurse_local.py` 和 `tts/nurse_clone.py`。

离线模型来自 [sherpa-onnx 的五说话人中文 VITS 发布页](https://huggingface.co/csukuangfj/sherpa-onnx-vits-zh-ll)。重建服务器时，用 `huggingface_hub.snapshot_download(repo_id="csukuangfj/sherpa-onnx-vits-zh-ll", local_dir="/root/autodl-tmp/zh-ll-hf")` 下载模型，安装 `sherpa-onnx==1.13.8`，再运行 `python /root/demo_backend/generate_local_fallback_audio.py` 生成同音色的 19 条兜底语音。当前服务器已完成这些步骤，`model.onnx` SHA-256 为 `6c349bdd73dc928234dd7bc86929748bba32cd5264d32d915bf7b7aa0595965b`。模型与语音文件不需要 API 密钥。

## 操作顺序

1. 选择“王阿姨”或“林先生”病例，等待实时画面和开场白。
2. 按住麦克风说话并在松开后发送，或打字后按 Enter。右上角显示轮次和计时。
3. 患者说话时可点击“打断说话”。
4. 结束实训并二次确认，生成五维报告；报告 URL 带 `session_id`，可刷新重开。
5. 报告支持打印或在浏览器保存 PDF。

## 已知限制与后续计划

- 当前产品流程按单场演示设计；桌面端和手机 Safari/Chrome 均可播放，语音识别依赖 Web Speech API 和浏览器权限。
- 两位患者使用各自视频中提取的授权声音。SoulX Lite 输出固定为 512×512，网页保持原比例居中展示，不拉伸人物。
- 两个病例各采用 50 条已审核应答来保证 4 秒内开口和文字、声音、口型一致；它不是开放域任意文本的实时声纹合成产品。对话模型不能编造病例未提供的检查结果、生活经历或其他疾病。
- 可用 `python generate_local_fallback_audio.py` 重新制作离线声线的整句预设语音；原 `generate_fallback_audio.py` 保留在线声线的重建能力。两个脚本均需在 LiveTalking 环境运行。
- V1.5 规划：教师端大屏、病历书写和本地 FunASR。

## 核心接口

`GET /api/demo/cases`、`POST /api/demo/session/start`、`POST /api/demo/chat`、`POST /api/demo/session/end`、`GET /api/demo/report/{session_id}`。另提供开场白接口 `POST /api/demo/session/greet` 和健康检查 `GET /api/demo/health`。错误体统一为中文 `{"error":"..."}`。
