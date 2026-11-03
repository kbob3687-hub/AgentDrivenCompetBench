"""Preserve Collector's actual fetched, redacted text during a live benchmark task."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from agents.collector.tools import FetchResult


class SourceCapture:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=False)
        self.entries: list[dict] = []
        self._write_index()

    def observe(self, result: FetchResult) -> None:
        entry = {
            "url": result.url,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "capture_kind": "collector_fetch_exact_redacted_text",
            "success": result.success,
            "error": result.error,
            "title": result.title,
            "fetch_method": result.fetch_method,
            "collector_snapshot_hash": result.snapshot_hash or None,
            "content_sha256": None,
            "content_path": None,
            "pii_redactions": result.pii_redactions,
        }
        if result.success and result.content:
            data = result.content.encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            path = self.directory / f"{digest}.txt"
            path.write_bytes(data)
            entry["content_sha256"] = digest
            entry["content_path"] = path.name
        self.entries.append(entry)
        self._write_index()

    def _write_index(self) -> None:
        path = self.directory / "index.json"
        path.write_text(json.dumps(self.entries, ensure_ascii=False, indent=2), encoding="utf-8")
