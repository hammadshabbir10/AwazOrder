"""Loads a local .env file into the environment (no extra dependency).

Values in .env win over the shell environment, so a key pasted into .env is
always the one used locally. On a host like Render there is no .env file and
the dashboard's environment variables are used as-is.
"""

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_env(path: Path = ENV_FILE) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if value:
            os.environ[key.strip()] = value


load_env()
