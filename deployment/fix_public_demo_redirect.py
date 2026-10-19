"""Make /demo work behind AutoDL's HTTPS port mapping."""

from pathlib import Path
import shutil


config = Path("/etc/nginx/sites-enabled/default")
source = config.read_text()
marker = "location = /demo {"
anchor = "location = /demo/ {"

if marker not in source:
    if source.count(anchor) != 1:
        raise SystemExit("Expected exactly one /demo/ nginx location")
    backup = Path("/etc/nginx/sites-available/default.before-demo-redirect")
    if not backup.exists():
        shutil.copy2(config, backup)
    source = source.replace(
        anchor,
        "location = /demo {\n"
        "\t\tabsolute_redirect off;\n"
        "\t\treturn 308 /demo/;\n"
        "\t}\n\n\t" + anchor,
        1,
    )
    config.write_text(source)
