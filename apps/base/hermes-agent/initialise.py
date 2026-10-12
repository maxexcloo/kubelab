"""Seed writable state without the image's root-only container supervisor."""

import os
import shutil
import subprocess
from pathlib import Path

installation = Path("/opt/hermes")
state = Path(os.environ["HERMES_HOME"])
state.mkdir(parents=True, exist_ok=True)
for name in ("home", "logs", "memories", "sessions", "skills", "workspace"):
    (state / name).mkdir(exist_ok=True)

# Refresh the repository-owned theme while preserving native user settings.
themes = state / "dashboard-themes"
themes.mkdir(exist_ok=True)
shutil.copyfile("/config/mono-large.yaml", themes / "mono-large.yaml")

# Keep native dashboard and CLI configuration edits across pod replacements.
for source, destination in (
    (Path("/config/config.yaml"), state / "config.yaml"),
    (installation / "docker/SOUL.md", state / "SOUL.md"),
):
    if not destination.exists():
        shutil.copyfile(source, destination)
        destination.chmod(0o600)

for script in ("scripts/docker_config_migrate.py", "tools/skills_sync.py"):
    subprocess.run([str(installation / ".venv/bin/python"), str(installation / script)], check=True)
