"""Authentication and per-user state API for the teacher exam practice app."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from threading import Lock
from typing import Any, Iterator

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse


APP_ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.getenv("EXAM_DB_PATH", APP_ROOT / "data" / "exam.db"))
COOKIE_NAME = "exam_session"
SESSION_DAYS = max(1, min(int(os.getenv("EXAM_SESSION_DAYS", "7")), 30))
SESSION_SECONDS = SESSION_DAYS * 24 * 60 * 60
COOKIE_SECURE = os.getenv("EXAM_COOKIE_SECURE", "1") != "0"
MAX_STATE_BYTES = 900_000
USERNAME_RE = re.compile(r"^[A-Za-z0-9_\u4e00-\u9fff]{3,20}$")
PBKDF2_ROUNDS = 310_000

app = FastAPI(title="师证通用户服务", docs_url=None, redoc_url=None, openapi_url=None)
db_lock = Lock()
failed_attempts: dict[str, list[float]] = {}


@contextmanager
def database() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
    finally:
        connection.close()


def init_database() -> None:
    with db_lock, database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                username_normalized TEXT NOT NULL UNIQUE,
                password_salt TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS invitation_codes (
                code TEXT PRIMARY KEY,
                created_at INTEGER NOT NULL,
                used_by INTEGER UNIQUE,
                used_at INTEGER,
                FOREIGN KEY (used_by) REFERENCES users(id)
            );
            CREATE TABLE IF NOT EXISTS user_states (
                user_id INTEGER PRIMARY KEY,
                state_json TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                expires_at INTEGER NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS sessions_user_id ON sessions(user_id);
            CREATE INDEX IF NOT EXISTS sessions_expires_at ON sessions(expires_at);
            """
        )
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        connection.commit()


@app.on_event("startup")
def on_startup() -> None:
    init_database()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    return forwarded.split(",", 1)[0].strip() or (request.client.host if request.client else "unknown")


def guard_attempts(request: Request) -> None:
    key = client_key(request)
    now = time.time()
    recent = [moment for moment in failed_attempts.get(key, []) if now - moment < 600]
    failed_attempts[key] = recent
    if len(recent) >= 10:
        raise HTTPException(status_code=429, detail="尝试次数过多，请十分钟后再试")


def record_failure(request: Request) -> None:
    key = client_key(request)
    failed_attempts.setdefault(key, []).append(time.time())


async def json_body(request: Request) -> dict[str, Any]:
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="请求格式必须为 JSON")
    try:
        value = await request.json()
    except Exception as error:
        raise HTTPException(status_code=400, detail="JSON 格式错误") from error
    if not isinstance(value, dict):
        raise HTTPException(status_code=400, detail="请求内容格式错误")
    return value


def validate_username(value: Any) -> tuple[str, str]:
    username = str(value or "").strip()
    if not USERNAME_RE.fullmatch(username):
        raise HTTPException(status_code=400, detail="用户名需为 3–20 位中文、字母、数字或下划线")
    return username, username.casefold()


def validate_password(value: Any) -> str:
    password = str(value or "")
    if len(password) < 8 or len(password) > 128:
        raise HTTPException(status_code=400, detail="密码长度需为 8–128 位")
    return password


def password_digest(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return base64.b64encode(digest).decode("ascii")


def create_session(connection: sqlite3.Connection, user_id: int) -> tuple[str, int]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
    now = int(time.time())
    expires_at = now + SESSION_SECONDS
    connection.execute(
        "INSERT INTO sessions(token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token_hash, user_id, now, expires_at),
    )
    return token, expires_at


def attach_cookie(response: Response, token: str, expires_at: int) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        expires=format_datetime(datetime.fromtimestamp(expires_at, tz=timezone.utc), usegmt=True),
        path="/",
        secure=COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )


def session_user(request: Request) -> sqlite3.Row:
    token = request.cookies.get(COOKIE_NAME, "")
    if not token:
        raise HTTPException(status_code=401, detail="请先登录")
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = int(time.time())
    with database() as connection:
        row = connection.execute(
            """
            SELECT u.id, u.username, u.created_at, s.expires_at
            FROM sessions s JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = ? AND s.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()
        if row is None:
            connection.execute("DELETE FROM sessions WHERE token_hash = ? OR expires_at <= ?", (token_hash, now))
            connection.commit()
            raise HTTPException(status_code=401, detail="登录状态已过期，请重新登录")
        return row


def user_payload(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "username": row["username"],
        "createdAt": row["created_at"] * 1000,
        "expiresAt": row["expires_at"] * 1000,
        "sessionDays": SESSION_DAYS,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    with database() as connection:
        users = connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        available = connection.execute("SELECT COUNT(*) FROM invitation_codes WHERE used_by IS NULL").fetchone()[0]
    return {"status": "ok", "users": users, "availableInvites": available, "sessionDays": SESSION_DAYS}


@app.post("/auth/register")
async def register(request: Request) -> JSONResponse:
    guard_attempts(request)
    body = await json_body(request)
    username, normalized = validate_username(body.get("username"))
    password = validate_password(body.get("password"))
    invitation = str(body.get("invitationCode") or "").strip().upper()
    if not invitation:
        raise HTTPException(status_code=400, detail="请输入邀请码")
    salt = secrets.token_bytes(16)
    digest = password_digest(password, salt)
    now = int(time.time())
    try:
        with db_lock, database() as connection:
            connection.execute("BEGIN IMMEDIATE")
            invite = connection.execute(
                "SELECT code, used_by FROM invitation_codes WHERE code = ?", (invitation,)
            ).fetchone()
            if invite is None or invite["used_by"] is not None:
                connection.rollback()
                record_failure(request)
                raise HTTPException(status_code=400, detail="邀请码无效或已被使用")
            cursor = connection.execute(
                """INSERT INTO users(username, username_normalized, password_salt, password_hash, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (username, normalized, base64.b64encode(salt).decode("ascii"), digest, now),
            )
            user_id = int(cursor.lastrowid)
            connection.execute(
                "UPDATE invitation_codes SET used_by = ?, used_at = ? WHERE code = ? AND used_by IS NULL",
                (user_id, now, invitation),
            )
            connection.execute(
                "INSERT INTO user_states(user_id, state_json, updated_at) VALUES (?, ?, ?)",
                (user_id, json.dumps({"profile": None, "session": None}), now),
            )
            token, expires_at = create_session(connection, user_id)
            connection.commit()
    except sqlite3.IntegrityError as error:
        record_failure(request)
        if "username_normalized" in str(error):
            raise HTTPException(status_code=409, detail="该用户名已被注册") from error
        raise HTTPException(status_code=409, detail="注册信息已存在") from error
    response = JSONResponse({"user": {"id": user_id, "username": username, "createdAt": now * 1000, "expiresAt": expires_at * 1000, "sessionDays": SESSION_DAYS}})
    attach_cookie(response, token, expires_at)
    return response


@app.post("/auth/login")
async def login(request: Request) -> JSONResponse:
    guard_attempts(request)
    body = await json_body(request)
    _, normalized = validate_username(body.get("username"))
    password = validate_password(body.get("password"))
    with db_lock, database() as connection:
        row = connection.execute(
            "SELECT id, username, created_at, password_salt, password_hash FROM users WHERE username_normalized = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            record_failure(request)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        salt = base64.b64decode(row["password_salt"])
        candidate = password_digest(password, salt)
        if not hmac.compare_digest(candidate, row["password_hash"]):
            record_failure(request)
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        # Keep other valid device sessions so the same account can be used on
        # phone and desktop at the same time. Expired sessions are still pruned.
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
        token, expires_at = create_session(connection, row["id"])
        old_sessions = connection.execute(
            "SELECT token_hash FROM sessions WHERE user_id = ? ORDER BY created_at DESC, rowid DESC LIMIT -1 OFFSET 5",
            (row["id"],),
        ).fetchall()
        if old_sessions:
            connection.executemany("DELETE FROM sessions WHERE token_hash = ?", [(item["token_hash"],) for item in old_sessions])
        connection.commit()
    response = JSONResponse({"user": {"id": row["id"], "username": row["username"], "createdAt": row["created_at"] * 1000, "expiresAt": expires_at * 1000, "sessionDays": SESSION_DAYS}})
    attach_cookie(response, token, expires_at)
    return response


@app.post("/auth/logout")
def logout(request: Request) -> JSONResponse:
    token = request.cookies.get(COOKIE_NAME, "")
    if token:
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with db_lock, database() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            connection.commit()
    response = JSONResponse({"ok": True})
    response.delete_cookie(COOKIE_NAME, path="/", secure=COOKIE_SECURE, httponly=True, samesite="lax")
    return response


@app.get("/auth/me")
def me(request: Request) -> dict[str, Any]:
    return {"user": user_payload(session_user(request))}


@app.get("/auth/status")
def auth_status(request: Request) -> dict[str, Any]:
    """Return an anonymous status without producing a browser console 401 on first visit."""
    try:
        user = session_user(request)
    except HTTPException as error:
        if error.status_code == 401:
            return {"user": None}
        raise
    return {"user": user_payload(user)}


@app.get("/state")
def get_state(request: Request) -> dict[str, Any]:
    user = session_user(request)
    with database() as connection:
        row = connection.execute("SELECT state_json, updated_at FROM user_states WHERE user_id = ?", (user["id"],)).fetchone()
    if row is None:
        return {"profile": None, "session": None, "updatedAt": None}
    try:
        state = json.loads(row["state_json"])
    except json.JSONDecodeError:
        state = {"profile": None, "session": None}
    return {"profile": state.get("profile"), "session": state.get("session"), "updatedAt": row["updated_at"] * 1000}


@app.put("/state")
async def put_state(request: Request) -> dict[str, Any]:
    user = session_user(request)
    body = await json_body(request)
    if not isinstance(body.get("profile"), dict) or (body.get("session") is not None and not isinstance(body.get("session"), dict)):
        raise HTTPException(status_code=400, detail="学习数据格式错误")
    serialized = json.dumps(
        {"profile": body["profile"], "session": body.get("session")},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(serialized.encode("utf-8")) > MAX_STATE_BYTES:
        raise HTTPException(status_code=413, detail="学习数据超过容量限制")
    now = int(time.time())
    with db_lock, database() as connection:
        connection.execute(
            """INSERT INTO user_states(user_id, state_json, updated_at) VALUES (?, ?, ?)
               ON CONFLICT(user_id) DO UPDATE SET state_json = excluded.state_json, updated_at = excluded.updated_at""",
            (user["id"], serialized, now),
        )
        connection.commit()
    return {"ok": True, "updatedAt": now * 1000}
