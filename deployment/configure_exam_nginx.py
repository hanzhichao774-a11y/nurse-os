"""Install the /exam entry routes without changing the existing /demo routes."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


path = Path("/etc/nginx/sites-enabled/default")
text = path.read_text(encoding="utf-8")
static_route = """
	# 高校教师资格刷题工具。静态资源继续由通用 location / 提供。
	location = /exam {
		absolute_redirect off;
		return 308 /exam/;
	}

	location = /exam/ {
		proxy_pass http://127.0.0.1:8010/exam/index.html;
	}

"""
api_route = """
	# 师证通登录、注册与用户学习数据服务。
	location ^~ /api/exam/ {
		proxy_pass http://127.0.0.1:8002/;
		proxy_set_header Host $host;
		proxy_set_header X-Real-IP $remote_addr;
		proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
		proxy_set_header X-Forwarded-Proto $scheme;
		proxy_read_timeout 30s;
	}

"""
changed = False
backup_dir = Path("/root/demo_backend/backup/nginx")
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / f"default.before-exam-auth-{datetime.now():%Y%m%d-%H%M%S}"
if "location = /exam {" not in text:
    marker = "\tlocation = /demo {"
    if marker not in text:
        raise RuntimeError("nginx /demo entry route was not found")
    text = text.replace(marker, static_route + marker, 1)
    changed = True
if "location ^~ /api/exam/" not in text:
    marker = "\tlocation = /exam {"
    if marker not in text:
        raise RuntimeError("nginx /exam entry route was not found")
    text = text.replace(marker, api_route + marker, 1)
    changed = True
if changed:
    shutil.copy2(path, backup)
    path.write_text(text, encoding="utf-8")
    print(f"updated {path}; backup {backup}")
else:
    print("/exam routes already present")
