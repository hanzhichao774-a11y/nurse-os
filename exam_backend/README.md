# 师证通用户服务

独立的 FastAPI 服务，监听 `127.0.0.1:8002`，由 nginx 暴露为 `/api/exam/`。

- 邀请码一次性使用。
- 密码使用 PBKDF2-HMAC-SHA256 和独立随机盐保存。
- 登录 Cookie 有效期 7 天，设置 `HttpOnly`、`Secure` 和 `SameSite=Lax`。
- 用户的错题、收藏、进度和未完成练习以用户 ID 隔离保存在 SQLite。
- 数据库位于服务器 `/root/exam_backend/data/exam.db`。
