# 政工通用户服务

政工师刷题系统的独立 FastAPI 服务。生产环境监听 `127.0.0.1:8003`，由 Nginx 暴露为 `/api/political-exam/`。

- 用户名和密码可直接注册，无需邀请码。
- 密码使用 PBKDF2-HMAC-SHA256 和独立随机盐保存。
- 登录 Cookie 默认有效 7 天，设置 `HttpOnly` 和 `SameSite=Lax`；HTTPS 部署时通过 `POLITICAL_EXAM_COOKIE_SECURE=1` 启用 `Secure`。
- 每个用户的错题、收藏、进度和未完成练习按用户 ID 隔离保存在 SQLite。
- 生产数据库建议放在 `/var/lib/political-exam/political-exam.db`，不要提交到仓库。

## 环境变量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `POLITICAL_EXAM_DB_PATH` | `political_exam_backend/data/political-exam.db` | SQLite 数据库路径 |
| `POLITICAL_EXAM_SESSION_DAYS` | `7` | Cookie 有效天数，范围 1–30 |
| `POLITICAL_EXAM_COOKIE_SECURE` | `1` | HTTPS 使用 `1`，仅 HTTP 测试环境使用 `0` |

启动示例：

```bash
POLITICAL_EXAM_DB_PATH=/var/lib/political-exam/political-exam.db \
POLITICAL_EXAM_COOKIE_SECURE=0 \
uvicorn app:app --host 127.0.0.1 --port 8003
```
