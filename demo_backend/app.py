"""护语者演示服务：病例、对话编排、数字人驱动和评分。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from dotenv import dotenv_values
from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from openai import OpenAI
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from case_fallback import (
    LIN_HAO_RESPONSE_BANK,
    WANG_AYI_RESPONSE_BANK,
    lin_hao_response,
    lin_hao_response_catalog,
    select_lin_hao_response,
    select_reply,
    select_wang_ayi_response,
    wang_ayi_response,
    wang_ayi_response_catalog,
)
from avatar_provider import soulx_for_case, valid_session_id
from mobile_media import MobileMedia
from scoring_fallback import fallback_report as score_without_model


ROOT = Path(__file__).resolve().parent
DATA = Path(os.getenv("DEMO_DATA_DIR", ROOT / "data"))
SESSIONS = DATA / "sessions"
CASES = DATA / "cases"
PROMPTS = ROOT / "prompts"
SESSIONS.mkdir(parents=True, exist_ok=True)
LOGGER = logging.getLogger("hu-yu-zhe")
LOGGER.setLevel(logging.INFO)
LOGGER.addHandler(logging.StreamHandler())
LOGGER.propagate = False
LOCK = asyncio.Lock()  # 现场演示只支持一个会话，防止结束和对话并行覆盖记录。
CLIENT_LOCK = threading.Lock()
CLIENT_SIGNATURE: tuple[str, str] | None = None
CLIENTS: dict[float, OpenAI] = {}

app = FastAPI(title="护语者 Demo", docs_url=None, redoc_url=None)
MOBILE_MEDIA = MobileMedia(ROOT / "mobile_hls", os.getenv("DEMO_FFMPEG_PATH", "/usr/bin/ffmpeg"))

DIMENSIONS = [
    ("病史采集完整性", 30),
    ("共情与情绪回应", 20),
    ("健康教育准确性", 20),
    ("沟通技巧与语言通俗性", 15),
    ("职业素养与人文关怀", 15),
]
EMOTIONS = {"焦虑", "平静", "抗拒", "感激"}


class StartInput(BaseModel):
    case_id: str


class ChatInput(BaseModel):
    session_id: str
    text: str = Field(min_length=1, max_length=500)


class SessionInput(BaseModel):
    session_id: str


def settings() -> dict[str, str]:
    # 每次请求重读 .env，现场更换 key 后不需要重启服务。
    values = {k: str(v) for k, v in dotenv_values(ROOT / ".env").items() if v is not None}
    values.update({
        k: v for k, v in os.environ.items()
        if k.startswith(("LLM_", "LIVETALKING_", "SOULX_", "AVATAR_"))
    })
    return values


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def session_path(session_id: str) -> Path:
    if not re.fullmatch(r"\d{8}_\d{6}_[0-9a-f]{4}", session_id):
        raise HTTPException(400, "实训编号格式不正确")
    return SESSIONS / f"{session_id}.json"


def read_session(session_id: str) -> dict[str, Any]:
    path = session_path(session_id)
    if not path.is_file():
        raise HTTPException(404, "找不到这场实训记录")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HTTPException(500, "实训记录读取失败") from None


def save_session(data: dict[str, Any]) -> None:
    path = session_path(data["session_id"])
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def case_data(case_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9_]+", case_id):
        raise HTTPException(400, "病例编号不正确")
    path = CASES / f"{case_id}.json"
    if not path.is_file():
        raise HTTPException(404, "找不到这个病例")
    return json.loads(path.read_text(encoding="utf-8"))


def parse_json(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            raise ValueError("模型没有返回 JSON") from None
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("模型返回格式不正确")
    return value


def infer_emotion(reply: str) -> str:
    if any(word in reply for word in ("谢谢", "多亏", "感激")):
        return "感激"
    if any(word in reply for word in ("你们年轻", "别烦", "不懂")):
        return "抗拒"
    if any(word in reply for word in ("怕", "慌", "唉", "担心", "会不会")):
        return "焦虑"
    return "平静"


def llm_client(cfg: dict[str, str], timeout: float) -> OpenAI:
    """复用 HTTPS 连接；更换 .env 密钥或地址时关闭旧连接。"""
    global CLIENT_SIGNATURE
    signature = (cfg["LLM_API_KEY"], cfg.get("LLM_BASE_URL", ""))
    with CLIENT_LOCK:
        if CLIENT_SIGNATURE != signature:
            for old in CLIENTS.values():
                old.close()
            CLIENTS.clear()
            CLIENT_SIGNATURE = signature
        if timeout not in CLIENTS:
            transport = httpx.Client(
                timeout=timeout,
                limits=httpx.Limits(max_connections=8, max_keepalive_connections=4, keepalive_expiry=120.0),
                follow_redirects=True,
            )
            CLIENTS[timeout] = OpenAI(
                api_key=signature[0], base_url=signature[1] or None,
                timeout=timeout, max_retries=0, http_client=transport,
            )
        return CLIENTS[timeout]


def llm_json(system_prompt: str, messages: list[dict[str, str]], timeout: float, allow_text_reply: bool = False, attempts: int = 2) -> dict[str, Any]:
    cfg = settings()
    if not cfg.get("LLM_API_KEY") or not cfg.get("LLM_MODEL"):
        raise RuntimeError("尚未配置大模型")
    client = llm_client(cfg, timeout)
    for attempt in range(attempts):
        prompt_messages = [{"role": "system", "content": system_prompt}, *messages]
        if attempt:
            prompt_messages[-1] = {
                **prompt_messages[-1],
                "content": prompt_messages[-1]["content"] + "\n\n务必输出非空、完整、可解析的JSON对象，禁止只输出空白。",
            }
        kwargs: dict[str, Any] = {
            "model": cfg["LLM_MODEL"],
            "messages": prompt_messages,
            "temperature": 0.2,
            "max_tokens": 1500 if timeout > 15 else 200,
            "extra_body": {"thinking": {"type": "disabled"}},
        }
        if (not attempt and not allow_text_reply) or (attempt and allow_text_reply):
            kwargs["response_format"] = {"type": "json_object"}
        started = time.monotonic()
        completion = client.chat.completions.create(**kwargs)
        content = (completion.choices[0].message.content or "").strip()
        LOGGER.info(
            "模型调用：场景=%s 尝试=%d 耗时=%.2fs 字符数=%d 结束原因=%s",
            "评分" if timeout > 15 else "对话", attempt + 1,
            time.monotonic() - started, len(content), completion.choices[0].finish_reason,
        )
        if content:
            try:
                return parse_json(content)
            except (ValueError, json.JSONDecodeError):
                if allow_text_reply and len(content) <= 120:
                    return {"reply": content, "emotion": infer_emotion(content)}
    raise ValueError("模型未返回有效 JSON")


def transcript_messages(transcript: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {"role": "assistant" if item["role"] == "patient" else "user", "content": item["text"]}
        for item in transcript
        if item.get("turn", 0) > 0
    ]


async def select_reviewed_lin_hao_reply(
    system_prompt: str,
    transcript: list[dict[str, Any]],
    current_text: str,
) -> tuple[str, str, str, bool]:
    """Use the LLM as a contextual selector over reviewed, voiced lines.

    This keeps open-ended conversational understanding while making it
    impossible for the spoken patient to invent a fact or choose text without
    a byte-identical cloned-voice recording.
    """

    recent_ids = [
        str(item["response_id"])
        for item in transcript
        if item.get("role") == "patient" and item.get("response_id")
    ]
    fallback_id, fallback_reply, fallback_emotion, fallback_intent = select_lin_hao_response(
        current_text, recent_ids,
    )
    case_rules = system_prompt.split("【输出格式】", 1)[0].rstrip()
    selector_system = f"""{case_rules}

【本轮任务：从审核应答库中选择】
你不能自由创作回复。请结合完整对话历史和护士本轮话语，从下面应答库选择语义最贴切的一条。
- 要回应护士真正表达的意思，也要承接上一轮上下文；不能只做关键词匹配。
- 护士敷衍、催促、安抚、解释、追问、使用术语或讨论无关话题时，要选择相应态度。
- 只能选择下列 response_id，不得改写句子，不得补充病例事实。
- 最近用过的句子优先换成同类其他表达，避免机械重复。
- 只输出 JSON：{{"response_id":"候选ID"}}

【审核应答库】
{lin_hao_response_catalog(recent_ids)}"""
    messages = transcript_messages(transcript) + [{
        "role": "user",
        "content": current_text + "\n\n请选择最自然、最贴合上下文且不越过病例边界的 response_id。",
    }]
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(llm_json, selector_system, messages, 2.0, False, 1),
            timeout=1.65,
        )
        response_id = str(raw.get("response_id", "")).strip()
        reply, emotion, intent = lin_hao_response(response_id)
        if response_id in set(recent_ids[-2:]):
            alternatives = [
                candidate_id for candidate_id, candidate in LIN_HAO_RESPONSE_BANK.items()
                if candidate[2] == intent and candidate_id not in set(recent_ids[-4:])
            ]
            if alternatives:
                response_id = alternatives[0]
                reply, emotion, _ = lin_hao_response(response_id)
        LOGGER.info("年轻男性应答选择：%s（意图=%s）", response_id, intent)
        return response_id, reply, emotion, False
    except Exception as exc:
        LOGGER.warning(
            "年轻男性语义选择失败，使用安全本地选择（%s）：%s %s",
            fallback_intent, type(exc).__name__, str(exc)[:120],
        )
        return fallback_id, fallback_reply, fallback_emotion, True


async def select_reviewed_wang_ayi_reply(
    system_prompt: str,
    transcript: list[dict[str, Any]],
    current_text: str,
) -> tuple[str, str, str, bool]:
    """Select one reviewed Wang Ayi sentence with full conversational context."""

    recent_ids = [
        str(item["response_id"])
        for item in transcript
        if item.get("role") == "patient" and item.get("response_id")
    ]
    fallback_id, fallback_reply, fallback_emotion, fallback_intent = select_wang_ayi_response(
        current_text, recent_ids,
    )
    case_rules = system_prompt.split("【输出格式】", 1)[0].rstrip()
    selector_system = f"""{case_rules}

【本轮任务：从审核应答库中选择】
你不能自由创作回复。请结合完整对话历史和护士本轮话语，从下面应答库选择语义最贴切的一条。
- 要回应护士真正表达的意思，也要承接上一轮上下文；不能只做关键词匹配。
- 护士敷衍、催促、安抚、解释、追问、使用术语或讨论无关话题时，要选择相应态度。
- 只能选择下列 response_id，不得改写句子，不得补充病例事实。
- 最近用过的句子优先换成同类其他表达，避免机械重复。
- 只输出 JSON：{{"response_id":"候选ID"}}

【审核应答库】
{wang_ayi_response_catalog(recent_ids)}"""
    messages = transcript_messages(transcript) + [{
        "role": "user",
        "content": current_text + "\n\n请选择最自然、最贴合上下文且不越过病例边界的 response_id。",
    }]
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(llm_json, selector_system, messages, 2.0, False, 1),
            timeout=1.65,
        )
        response_id = str(raw.get("response_id", "")).strip()
        reply, emotion, intent = wang_ayi_response(response_id)
        if response_id in set(recent_ids[-2:]):
            alternatives = [
                candidate_id for candidate_id, candidate in WANG_AYI_RESPONSE_BANK.items()
                if candidate[2] == intent and candidate_id not in set(recent_ids[-4:])
            ]
            if alternatives:
                response_id = alternatives[0]
                reply, emotion, _ = wang_ayi_response(response_id)
        LOGGER.info("王阿姨应答选择：%s（意图=%s）", response_id, intent)
        return response_id, reply, emotion, False
    except Exception as exc:
        LOGGER.warning(
            "王阿姨语义选择失败，使用安全本地选择（%s）：%s %s",
            fallback_intent, type(exc).__name__, str(exc)[:120],
        )
        return fallback_id, fallback_reply, fallback_emotion, True


async def drive_avatar(session_id: str, text: str, voice: str) -> bool:
    base = settings().get("LIVETALKING_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    async with httpx.AsyncClient(timeout=2.4) as client:
        payload = {"sessionid": session_id, "type": "echo", "text": text, "tts": {"voice": voice, "ref_file": voice}}
        for attempt in range(2):
            try:
                response = await client.post(f"{base}/human", json=payload)
                result = response.json()
                if response.is_success and result.get("code") == 0:
                    return True
                LOGGER.warning("数字人驱动失败，状态码：%s", response.status_code)
            except (httpx.HTTPError, ValueError):
                LOGGER.warning("数字人驱动网络异常", exc_info=True)
            if attempt == 0:
                await asyncio.sleep(0.15)
    return False


async def drive_cached_avatar(session_id: str, category: str, text: str, voice: str, variant: str = "full") -> bool:
    """Use a local recording when the model or external TTS is slow."""
    directory = ROOT / "assets" / "fallback_audio"
    audio_path = directory / (f"{category}.wav" if variant == "full" else f"{variant}/{category}.wav")
    if audio_path.is_file():
        base = settings().get("LIVETALKING_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
        audio = audio_path.read_bytes()
        async with httpx.AsyncClient(timeout=3.0) as client:
            for attempt in range(2):
                try:
                    response = await client.post(
                        f"{base}/humanaudio",
                        data={"sessionid": session_id},
                        files={"file": (audio_path.name, audio, "audio/wav")},
                    )
                    if response.is_success and response.json().get("code") == 0:
                        return True
                    LOGGER.warning("缓存语音驱动失败，状态码：%s", response.status_code)
                except (httpx.HTTPError, ValueError):
                    LOGGER.warning("缓存语音驱动网络异常", exc_info=True)
                if attempt == 0:
                    await asyncio.sleep(0.15)
    return await drive_avatar(session_id, text, voice)


def cached_audio_path(category: str, variant: str = "full") -> Path | None:
    directory = ROOT / "assets" / "fallback_audio"
    path = directory / (f"{category}.wav" if variant == "full" else f"{variant}/{category}.wav")
    return path if path.is_file() else None


async def play_avatar(
    data: dict[str, Any],
    text: str,
    voice: str,
    category: str | None = None,
    variant: str = "full",
) -> bool:
    """Route speech through the renderer selected when the session started."""

    if data.get("avatar_provider") == "soulx":
        path = cached_audio_path(category, variant) if category else None
        return await soulx_for_case(data["case_id"]).play(data["session_id"], text, path)
    if category:
        return await drive_cached_avatar(data["session_id"], category, text, voice, variant)
    return await drive_avatar(data["session_id"], text, voice)


def fallback_report(data: dict[str, Any]) -> dict[str, Any]:
    """外部评分服务异常时，仍根据本场学生原话生成可追溯的报告。"""
    return score_without_model(data["transcript"], data["case_id"])


def normalize_report(raw: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    dimensions = raw.get("dimensions")
    if not isinstance(dimensions, list) or len(dimensions) != 5:
        raise ValueError("评分维度不完整")
    result = []
    for item, (name, weight) in zip(dimensions, DIMENSIONS):
        if item.get("name") != name:
            raise ValueError("评分维度顺序不正确")
        score = max(0, min(weight, round(float(item["score"]))))
        comment = str(item.get("comment", "")).strip()
        if not comment:
            raise ValueError("评语为空")
        if not re.search(r"第\s*\d+\s*轮", comment) and "未涉及" not in comment:
            raise ValueError("评语缺少对话轮次依据")
        result.append({"name": name, "weight": weight, "score": score, "comment": comment})
    suggestions = raw.get("suggestions", [])
    if not isinstance(suggestions, list) or len(suggestions) < 3:
        raise ValueError("改进建议不足三条")
    suggestions = [str(x).strip() for x in suggestions[:3]]
    if any(len(item) < 8 for item in suggestions):
        raise ValueError("改进建议不够具体")
    if len([x for x in data["transcript"] if x["role"] == "student"]) < 4 and not suggestions[0].startswith("对话轮次不足"):
        suggestions[0] = "对话轮次不足，评分仅供参考；" + suggestions[0]
    case = case_data(data["case_id"])
    return {
        "session_id": data["session_id"],
        "case_id": data["case_id"],
        "case": {
            "name": case["name"],
            "display_name": case["display_name"],
            "age": case["age"],
            "report_subtitle": case.get("report_subtitle", "标准化病人"),
        },
        "total_score": sum(x["score"] for x in result),
        "dimensions": result,
        "suggestions": suggestions,
        "transcript": data["transcript"],
        "created_at": now(),
    }


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    message = {404: "找不到请求的页面或资源", 405: "不支持该请求方式"}.get(exc.status_code) if exc.detail in ("Not Found", "Method Not Allowed") else str(exc.detail)
    return JSONResponse({"error": message}, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, __: RequestValidationError):
    return JSONResponse({"error": "提交内容不完整或格式不正确"}, status_code=422)


@app.exception_handler(Exception)
async def server_error(_: Request, exc: Exception):
    LOGGER.exception("服务异常：%s", type(exc).__name__)
    return JSONResponse({"error": "服务暂时不可用，请稍后再试"}, status_code=500)


@app.get("/health")
def health():
    cfg = settings()
    return {"status": "ok", "llm_configured": bool(cfg.get("LLM_API_KEY") and cfg.get("LLM_MODEL"))}


@app.get("/cases")
def cases():
    entries = []
    for path in (path for path in CASES.glob("*.json") if not path.name.startswith(".")):
        obj = json.loads(path.read_text(encoding="utf-8"))
        public_keys = (
            "case_id", "name", "display_name", "age", "tags", "difficulty",
            "brief", "goals", "available", "poster", "poster_alt",
            "care_context", "report_subtitle", "order", "avatar_provider",
        )
        entries.append({key: obj.get(key) for key in public_keys})
    entries.sort(key=lambda item: (item.get("order") or 999, item["case_id"]))
    entries += [
        {"case_id": "li_shushu", "name": "李建国", "display_name": "李叔叔", "age": 72, "tags": ["高血压", "独居型", "沟通训练·进阶"], "difficulty": 3, "brief": "即将开放", "goals": [], "available": False},
        {"case_id": "chen_nainai", "name": "陈美芳", "display_name": "陈奶奶", "age": 81, "tags": ["术后康复", "抗拒型", "沟通训练·进阶"], "difficulty": 4, "brief": "即将开放", "goals": [], "available": False},
    ]
    return {"cases": entries}


@app.post("/session/start")
async def start_session(payload: StartInput):
    case = case_data(payload.case_id)
    if not case["available"]:
        raise HTTPException(400, "该病例尚未开放")
    requested_provider = case.get("avatar_provider", "livetalking")
    provider = requested_provider
    if requested_provider == "soulx" and not await soulx_for_case(case["case_id"]).available():
        provider = "livetalking"
        LOGGER.warning("SoulX renderer is unavailable; using LiveTalking for %s", case["case_id"])
    async with LOCK:
        while True:
            session_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(2)
            if not session_path(session_id).exists():
                break
        save_session({
            "session_id": session_id,
            "case_id": case["case_id"],
            "avatar_provider": provider,
            "started_at": now(),
            "ended_at": None,
            "transcript": [],
            "report": None,
        })
    return {"session_id": session_id, "avatar_provider": provider}


@app.websocket("/avatar/ws/{session_id}")
async def avatar_stream(websocket: WebSocket, session_id: str):
    if not valid_session_id(session_id):
        await websocket.close(code=1008)
        return
    try:
        data = read_session(session_id)
    except HTTPException:
        await websocket.close(code=1008)
        return
    if data.get("ended_at") or data.get("avatar_provider") != "soulx":
        await websocket.close(code=1008)
        return
    try:
        await soulx_for_case(data["case_id"]).serve(session_id, websocket)
    except Exception as exc:
        LOGGER.warning("SoulX browser stream ended for %s: %s", session_id, exc)


@app.post("/avatar/interrupt")
async def interrupt_avatar(payload: SessionInput):
    data = read_session(payload.session_id)
    if data.get("avatar_provider") == "soulx":
        return {"interrupted": await soulx_for_case(data["case_id"]).interrupt(payload.session_id)}
    base = settings().get("LIVETALKING_BASE_URL", "http://127.0.0.1:8010").rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.post(
                f"{base}/interrupt_talk", json={"sessionid": payload.session_id},
            )
        result = response.json()
        return {"interrupted": response.is_success and result.get("code") == 0}
    except (httpx.HTTPError, ValueError):
        return {"interrupted": False}


@app.post("/session/greet")
async def greet(payload: SessionInput):
    async with LOCK:
        data = read_session(payload.session_id)
        if data["ended_at"]:
            raise HTTPException(409, "这场实训已经结束")
        if data["transcript"]:
            return {"reply": data["transcript"][0]["text"]}
        case = case_data(data["case_id"])
        reply = case["greeting"]
        emotion = case.get("greeting_emotion", "焦虑")
        cached_greeting = case["case_id"] in {"human_candidate", "wang_ayi"}
        played = await play_avatar(
            data,
            reply,
            case["tts_voice"],
            category="greeting" if cached_greeting else None,
            variant=case["case_id"] if cached_greeting else "full",
        )
        data["transcript"].append({"role": "patient", "text": reply, "emotion": emotion, "turn": 0})
        save_session(data)
        return {"reply": reply, "emotion": emotion, "turn": 0, "avatar_played": played}


@app.post("/session/mobile-media")
async def start_mobile_media(payload: SessionInput):
    data = read_session(payload.session_id)
    if data["ended_at"]:
        raise HTTPException(409, "这场实训已经结束")
    try:
        await asyncio.to_thread(MOBILE_MEDIA.wait_ready, payload.session_id, data["case_id"])
    except (OSError, RuntimeError, TimeoutError) as exc:
        LOGGER.error("手机媒体流启动失败：%s", exc)
        raise HTTPException(503, "手机画面暂时无法连接，请重新进入实训") from None
    return {"url": f"/api/demo/mobile-media/{payload.session_id}/index.m3u8"}


@app.get("/mobile-media/{session_id}/{filename}")
def mobile_media_file(session_id: str, filename: str):
    read_session(session_id)
    if filename not in {"index.m3u8", "init.mp4"} and not re.fullmatch(r"index\d+\.m4s", filename):
        raise HTTPException(404, "找不到媒体文件")
    path = MOBILE_MEDIA.root / session_id / filename
    if not path.is_file():
        raise HTTPException(404, "媒体文件尚未生成")
    MOBILE_MEDIA.touch(session_id)
    media_type = "application/vnd.apple.mpegurl" if filename.endswith(".m3u8") else "video/mp4"
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.post("/session/mobile-media/stop")
def stop_mobile_media(payload: SessionInput):
    read_session(payload.session_id)
    MOBILE_MEDIA.stop(payload.session_id)
    return {"stopped": True}


@app.post("/chat")
async def chat(payload: ChatInput):
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "请输入要说的话")
    async with LOCK:
        data = read_session(payload.session_id)
        if data["ended_at"]:
            raise HTTPException(409, "这场实训已经结束")
        case = case_data(data["case_id"])
        turn = sum(x["role"] == "student" for x in data["transcript"]) + 1
        system_prompt = (ROOT / case["system_prompt_file"]).read_text(encoding="utf-8")
        response_id: str | None = None
        if case["case_id"] == "human_candidate":
            response_id, reply, emotion, used_fallback = await select_reviewed_lin_hao_reply(
                system_prompt, data["transcript"], text,
            )
            category = response_id
        elif case["case_id"] == "wang_ayi":
            response_id, reply, emotion, used_fallback = await select_reviewed_wang_ayi_reply(
                system_prompt, data["transcript"], text,
            )
            category = response_id
        else:
            fallback_reply, fallback_emotion, category = select_reply(text, case["case_id"])
            messages = transcript_messages(data["transcript"]) + [{"role": "user", "content": text + "\n\n请严格依据系统病例设定自然回答本轮问题；只输出reply和emotion的JSON对象，总字数不超过80字。任何病例中未明确给出的经历、检查结果、生命体征、生活习惯、用药情况或疾病都不得编造；不确定时请说不清楚并请护士或医生评估。"}]
            used_fallback = False
            try:
                raw = await asyncio.wait_for(
                    asyncio.to_thread(llm_json, system_prompt, messages, 1.8, True, 1),
                    timeout=1.6,
                )
                model_reply = str(raw["reply"]).strip()
                emotion = str(raw["emotion"])
                if not model_reply:
                    raise ValueError("患者回复内容不正确")
                if len(model_reply) > 80:
                    raise ValueError("患者回复超过80字")
                if category in {"diet", "glucose"}:
                    raise ValueError("病例未提供饮食或监测习惯，使用安全应答")
                if category == "lab_values" and re.search(r"(?:\d+(?:\.\d+)?|[一二三四五六七八九十]{1,3})(?:点|个|毫摩尔|mmol|mg)", model_reply, re.I):
                    raise ValueError("模型编造血糖数值")
                if category in {"foot", "wound"} and re.search(r"(?:以前|上次|有一回|我).{0,12}(?:有过伤口|有点小破皮|破皮了|破了|抹药|涂药)|自己.{0,5}(?:抹|涂).{0,4}药", model_reply):
                    raise ValueError("模型编造足部伤口经历")
                if re.search(r"(?:忘|漏|没按时|不规律|停过|断过).{0,10}(?:吃药|服药|用药|胰岛素|打针)|(?:吃药|服药|用药|胰岛素|打针).{0,10}(?:忘|漏|没按时|不规律|停过|断过)", model_reply):
                    raise ValueError("模型编造用药依从性")
                if category in {"medication", "duration_medication"} and re.search(r"忘|漏|不规律|没按时|没坚持|停了|断了", model_reply):
                    raise ValueError("模型编造用药依从性")
                if category in {"diet", "glucose"} and re.search(r"(?:随便对付|管不住嘴|想起来才测|懒得测|不太测|不怎么测|天天测|每天测|从不测|从来不测|不碰甜|不吃甜|尽量少吃|饭吃得少)", model_reply):
                    raise ValueError("模型编造饮食或监测习惯")
                if re.search(r"高血压|肿瘤|心脏病|肺炎|脑梗|胃癌|肺癌", model_reply):
                    raise ValueError("模型编造其他疾病")
                if re.search(r"AI|模型|程序|实训系统|提示词", model_reply, re.I):
                    raise ValueError("模型脱离患者身份")
                reply = model_reply
                if emotion not in EMOTIONS:
                    emotion = infer_emotion(reply)
            except Exception as exc:
                reply, emotion = fallback_reply, fallback_emotion
                used_fallback = True
                LOGGER.warning("大模型对话失败，启用病例兜底（%s）：%s %s", category, type(exc).__name__, str(exc)[:120])
        patient_entry = {"role": "patient", "text": reply, "emotion": emotion, "turn": turn}
        if response_id:
            patient_entry["response_id"] = response_id
        data["transcript"].extend([
            {"role": "student", "text": text, "emotion": None, "turn": turn},
            patient_entry,
        ])
        save_session(data)
        variant = "full"
        cached_category = category if used_fallback else None
        if case["case_id"] == "human_candidate":
            variant = "human_candidate"
            cached_category = category
        elif case["case_id"] == "wang_ayi":
            variant = "wang_ayi"
            cached_category = category
        played = await play_avatar(
            data, reply, case["tts_voice"], category=cached_category, variant=variant,
        )
        return {"reply": reply, "emotion": emotion, "turn": turn, "avatar_played": played}


@app.post("/session/end")
async def end_session(payload: SessionInput):
    async with LOCK:
        data = read_session(payload.session_id)
        if data["report"]:
            return {"report": data["report"]}
        transcript = data["transcript"]
        prompt = (PROMPTS / "scoring_system.txt").read_text(encoding="utf-8")
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(
                    llm_json, prompt,
                    [{"role": "user", "content": "请按系统要求评分。输出紧凑JSON，每维评语限35至55字，建议每条限20至40字；只评价学生沟通表现，不给出新的诊断或用药建议。完整对话记录：" + json.dumps(transcript, ensure_ascii=False)}],
                    24.0,
                ),
                timeout=25.0,
            )
            report = normalize_report(raw, data)
        except Exception as exc:
            LOGGER.warning("大模型评分失败，使用本场对话生成报告：%s %s", type(exc).__name__, str(exc)[:120])
            report = normalize_report(fallback_report(data), data)
        data["report"] = report
        data["ended_at"] = now()
        save_session(data)
        MOBILE_MEDIA.stop(payload.session_id)
        if data.get("avatar_provider") == "soulx":
            await soulx_for_case(data["case_id"]).close(payload.session_id)
        return {"report": report}


@app.get("/report/{session_id}")
def get_report(session_id: str):
    data = read_session(session_id)
    if not data["report"]:
        raise HTTPException(404, "评分报告尚未生成")
    return {"report": data["report"]}
