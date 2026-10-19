"""Install the same-origin SoulX WebSocket proxy into the active nginx site."""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


path = Path("/etc/nginx/sites-enabled/default")
text = path.read_text(encoding="utf-8")
route = """
	location ^~ /api/demo/avatar/ws/ {
		proxy_pass http://127.0.0.1:8000/avatar/ws/;
		proxy_http_version 1.1;
		proxy_set_header Upgrade $http_upgrade;
		proxy_set_header Connection "upgrade";
		proxy_read_timeout 3600s;
		proxy_send_timeout 3600s;
		proxy_buffering off;
	}

"""
if "location ^~ /api/demo/avatar/ws/" not in text:
    marker = "\tlocation /api/demo/ {"
    if marker not in text:
        raise RuntimeError("nginx demo API location was not found")
    backup_dir = Path("/root/demo_backend/backup/nginx")
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f"default.before-soulx-{datetime.now():%Y%m%d-%H%M%S}"
    shutil.copy2(path, backup)
    path.write_text(text.replace(marker, route + marker, 1), encoding="utf-8")
    print(f"updated {path}; backup {backup}")
else:
    print("SoulX websocket route already present")
