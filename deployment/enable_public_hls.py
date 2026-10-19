"""Expose MediaMTX HLS over the existing AutoDL HTTPS entry point."""

from pathlib import Path
import shutil


config = Path("/etc/nginx/sites-enabled/default")
source = config.read_text()
marker = "location ^~ /hls/ {"
anchor = "location /api/demo/ {"

if marker not in source:
    if source.count(anchor) != 1:
        raise SystemExit("Expected exactly one /api/demo/ nginx location")
    backup = Path("/etc/nginx/sites-available/default.before-public-hls")
    if not backup.exists():
        shutil.copy2(config, backup)
    source = source.replace(
        anchor,
        "location ^~ /hls/ {\n"
        "\t\tabsolute_redirect off;\n"
        "\t\tproxy_pass http://127.0.0.1:8887/;\n"
        "\t\tproxy_redirect ~^(/.*)$ /hls$1;\n"
        "\t\tproxy_read_timeout 60s;\n"
        "\t\tproxy_buffering off;\n"
        "\t}\n\n\t" + anchor,
        1,
    )
    config.write_text(source)
elif "location ^~ /hls/ {\n\t\tabsolute_redirect off;" not in source:
    source = source.replace(
        marker, marker + "\n\t\tabsolute_redirect off;", 1
    )
    config.write_text(source)
