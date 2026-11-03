"""Frozen snapshot bundles and replay fetch for reproducible benchmark arms.

A bundle is a directory holding index.json plus the captured *.txt files.
Replay serves the exact bytes captured at freeze time; a URL outside the
bundle or a hash mismatch raises instead of falling back to the network.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agents.collector.tools import FetchResult


class SnapshotReplayError(RuntimeError):
    """Raised instead of any silent live-network fallback."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SnapshotBundle:
    """Immutable URL -> captured text mapping loaded from a frozen directory."""

    def __init__(self, directory: Path, entries: list[dict[str, Any]]) -> None:
        self.directory = directory
        self.entries = entries
        self._by_url: dict[str, dict[str, Any]] = {}
        for entry in entries:
            if entry["url"] in self._by_url:
                raise SnapshotReplayError(f"Duplicate URL in bundle {directory}: {entry['url']}")
            self._by_url[entry["url"]] = entry

    @property
    def urls(self) -> list[str]:
        return sorted(self._by_url)

    @classmethod
    def load(cls, directory: Path) -> "SnapshotBundle":
        index = json.loads((directory / "index.json").read_text("utf-8"))
        if index.get("snapshot_kind") != "frozen_replay_bundle":
            raise SnapshotReplayError(
                f"{directory} is not a frozen replay bundle (snapshot_kind mismatch)"
            )
        for entry in index["entries"]:
            if not entry.get("success"):
                continue
            path = directory / entry["content_path"]
            digest = sha256(path.read_bytes())
            if digest != entry["content_sha256"]:
                raise SnapshotReplayError(
                    f"Snapshot hash mismatch for {entry['url']} in {directory}: "
                    f"{digest} != {entry['content_sha256']}"
                )
            entry["_text"] = path.read_text("utf-8")
        return cls(directory, index["entries"])

    def fetch(self, url: str) -> FetchResult:
        entry = self._by_url.get(url)
        if entry is None:
            raise SnapshotReplayError(
                f"URL not in frozen bundle {self.directory.name}: {url}; "
                "live fallback is forbidden during replay"
            )
        if not entry.get("success"):
            return FetchResult(
                url=url,
                success=False,
                error=entry.get("error") or "captured failure",
                fetch_method="snapshot_replay",
            )
        return FetchResult(
            url=url,
            title=entry.get("title") or "",
            content=entry["_text"],
            snapshot_hash=entry["content_sha256"],
            fetch_method="snapshot_replay",
        )


def freeze(run_dir: Path, task_ids: list[str], out_dir: Path) -> SnapshotBundle:
    """Merge per-task run-time snapshot dirs into one frozen bundle.

    The same URL captured with different content across tasks is a conflict,
    not a choice to make silently.
    """
    merged: dict[str, dict[str, Any]] = {}
    for task_id in task_ids:
        task_dir = run_dir / "source_snapshots" / task_id
        entries = json.loads((task_dir / "index.json").read_text("utf-8"))
        for entry in entries:
            url = entry["url"]
            digest = entry.get("content_sha256")
            if url in merged:
                if merged[url].get("content_sha256") != digest:
                    raise SnapshotReplayError(
                        f"Conflicting captures for {url}: "
                        f"{merged[url].get('content_sha256')} vs {digest}"
                    )
                continue
            record = {
                "url": url,
                "title": entry.get("title"),
                "success": bool(entry.get("success")),
                "error": entry.get("error"),
                "fetch_method": entry.get("fetch_method"),
                "observed_at": entry.get("observed_at"),
                "content_sha256": digest,
                "content_path": entry.get("content_path"),
                "_source_task": task_id,
            }
            merged[url] = record

    out_dir.mkdir(parents=True, exist_ok=False)
    for record in merged.values():
        if record["success"] and record["content_path"]:
            shutil.copyfile(
                run_dir / "source_snapshots" / record["_source_task"] / record["content_path"],
                out_dir / record["content_path"],
            )
    for record in merged.values():
        record.pop("_source_task", None)

    index = {
        "snapshot_kind": "frozen_replay_bundle",
        "frozen_at": _now(),
        "source_run": run_dir.name,
        "source_tasks": list(task_ids),
        "warning": "Replay serves frozen text only; freshness is bounded by observed_at.",
        "entries": [merged[url] for url in sorted(merged)],
    }
    (out_dir / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return SnapshotBundle.load(out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True, help="benchmark/results/<run_id>")
    parser.add_argument("--task", action="append", required=True, help="task_id inside the run")
    parser.add_argument("--out", type=Path, required=True, help="output bundle directory")
    args = parser.parse_args()
    bundle = freeze(args.run.resolve(), args.task, args.out.resolve())
    print(f"Froze {len(bundle.urls)} URLs -> {args.out}")


if __name__ == "__main__":
    main()
