"""Load project .env into os.environ (best-effort, no external deps)."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path | None = None) -> bool:
    root = Path(__file__).resolve().parents[2]
    env_path = path or (root / ".env")
    if not env_path.is_file():
        return False
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key and key not in os.environ:
            os.environ[key] = value
    return True
