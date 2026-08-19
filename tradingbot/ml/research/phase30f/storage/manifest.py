"""Broker collection manifest with file checksums."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tradingbot.ml.research.phase30f.storage.checksums import sha256_file


class ManifestStore:
    def __init__(self, path: Path, *, version: str) -> None:
        self.path = path
        self.version = version

    def load(self) -> dict[str, Any]:
        if not self.path.is_file():
            return self._empty()
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _empty(self) -> dict[str, Any]:
        return {
            "collector_version": self.version,
            "files": [],
            "collection_start_utc": None,
            "collection_end_utc": None,
        }

    def register_file(self, file_path: Path, *, kind: str, symbol: str = "") -> dict[str, Any]:
        entry = {
            "path": str(file_path),
            "kind": kind,
            "symbol": symbol,
            "sha256": sha256_file(file_path),
            "size_bytes": file_path.stat().st_size,
            "registered_utc": datetime.now(timezone.utc).isoformat(),
        }
        doc = self.load()
        if doc.get("collection_start_utc") is None:
            doc["collection_start_utc"] = entry["registered_utc"]
        doc["collection_end_utc"] = entry["registered_utc"]
        doc["collector_version"] = self.version
        paths = {f["path"] for f in doc.get("files", [])}
        if entry["path"] not in paths:
            doc.setdefault("files", []).append(entry)
        else:
            doc["files"] = [entry if f["path"] == entry["path"] else f for f in doc["files"]]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
        return entry

    def verify_all(self) -> list[dict[str, Any]]:
        doc = self.load()
        results = []
        for entry in doc.get("files", []):
            p = Path(entry["path"])
            ok = p.is_file() and sha256_file(p) == entry.get("sha256")
            results.append({"path": entry["path"], "valid": ok, "expected": entry.get("sha256")})
        return results
