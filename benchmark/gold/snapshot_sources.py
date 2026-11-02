"""Capture review-time source text for saved real benchmark records.

These are retrospective captures. They must never be described as the content
seen by the original Collector; the index records both timestamps explicitly.
"""

import argparse
import asyncio
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from agents.collector.tools import direct_http_fetch
from benchmark.evaluators.citation_eval import claim_slots

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def cited_urls(raw: dict) -> set[str]:
    profile = raw.get("state", {}).get("profile")
    urls = set()
    for _, claim in claim_slots(profile):
        if not isinstance(claim, dict):
            continue
        for source in claim.get("sources") or []:
            if isinstance(source, dict) and isinstance(source.get("url"), str):
                urls.add(source["url"])
    return urls


async def capture(corpus: Path = HERE / "corpus.json") -> dict:
    selection = json.loads(corpus.read_text("utf-8"))
    records = []
    all_urls = set()
    for item in selection["tasks"]:
        path = ROOT / item["raw"]
        data = path.read_bytes()
        raw = json.loads(data)
        urls = cited_urls(raw)
        original_hashes: dict[str, set[str]] = {}
        for claim in raw.get("state", {}).get("claims", []):
            if not isinstance(claim, dict):
                continue
            for source in claim.get("sources") or []:
                if not isinstance(source, dict):
                    continue
                url, digest = source.get("url"), source.get("snapshot_hash")
                if isinstance(url, str) and isinstance(digest, str) and digest:
                    original_hashes.setdefault(url, set()).add(digest)
        all_urls.update(urls)
        records.append(
            {
                "id": item["id"],
                "raw": item["raw"],
                "raw_sha256": sha256(data),
                "workflow_completed_at": raw.get("completed_at"),
                "urls": sorted(urls),
                "original_collector_hashes": {
                    url: sorted(values) for url, values in sorted(original_hashes.items())
                },
            }
        )

    directory = HERE / "snapshots"
    directory.mkdir(exist_ok=True)
    if (directory / "index.json").exists():
        raise FileExistsError("Snapshot index already exists; preserve it for reproducible review")
    semaphore = asyncio.Semaphore(3)

    async def fetch(url: str) -> dict:
        async with semaphore:
            result = await direct_http_fetch(url, timeout=30)
            captured_at = datetime.now(timezone.utc).isoformat()
            entry = {
                "url": url,
                "captured_at": captured_at,
                "capture_method": "direct_http_fetch",
                "success": result.success,
                "error": result.error,
                "title": result.title,
                "content_sha256": None,
                "content_path": None,
            }
            if result.success and result.content.strip():
                data = result.content.encode("utf-8")
                digest = sha256(data)
                path = directory / f"{digest}.txt"
                path.write_bytes(data)
                entry["content_sha256"] = digest
                entry["content_path"] = str(path.relative_to(HERE)).replace("\\", "/")
            return entry

    sources = await asyncio.gather(*(fetch(url) for url in sorted(all_urls)))
    index = {
        "snapshot_kind": "retrospective_review_capture",
        "warning": "Captured after the original workflow; cannot prove what Collector saw then.",
        "tasks": records,
        "sources": sources,
    }
    (directory / "index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return index


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=HERE / "corpus.json")
    args = parser.parse_args()
    index = asyncio.run(capture(args.corpus))
    print(
        f"Captured {sum(item['success'] for item in index['sources'])}/{len(index['sources'])} URLs"
    )
    print(HERE / "snapshots/index.json")


if __name__ == "__main__":
    main()
