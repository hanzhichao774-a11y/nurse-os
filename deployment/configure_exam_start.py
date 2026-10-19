"""Add the exam user service to the existing AutoDL startup script."""

from datetime import datetime
from pathlib import Path
import shutil


path = Path("/root/start.sh")
text = path.read_text(encoding="utf-8")
command = "bash /root/exam_backend/start.sh"
if command not in text:
    marker = "if ! curl --silent --fail http://127.0.0.1:8010/index-whep.html >/dev/null; then"
    if marker not in text:
        raise RuntimeError("LiveTalking startup marker not found")
    block = (
        "# Start the independent teacher-exam authentication and state service.\n"
        "if [ -x /root/exam_backend/start.sh ]; then\n"
        f"  {command}\n"
        "fi\n\n"
    )
    backup = path.with_name(f"start.sh.before-exam-{datetime.now():%Y%m%d-%H%M%S}")
    shutil.copy2(path, backup)
    path.write_text(text.replace(marker, block + marker, 1), encoding="utf-8")
    print(f"updated {path}; backup {backup}")
else:
    print("exam service startup already present")
