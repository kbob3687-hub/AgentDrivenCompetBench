"""Capture formal-case source pages once, then freeze one replay bundle per case.

Uses CollectorAgent's exact fetch chain (robots -> firecrawl -> http -> playwright,
including PII redaction) so each bundle holds the same text the Collector would
see. No LLM is called. Run this once; bundles are then immutable inputs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def entry_from(result: Any) -> dict[str, Any]:
    entry = {
        "url": result.url,
        "observed_at": now(),
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
        entry["content_sha256"] = digest
        entry["content_path"] = f"{digest}.txt"
    return entry


async def capture(cases_path: Path, results_root: Path, bundle_root: Path) -> dict[str, Any]:
    from agents.collector.agent import CollectorAgent
    from benchmark.replay import freeze
    from benchmark.runner import load_cases

    cases = load_cases(cases_path)
    agent = CollectorAgent()
    semaphore = asyncio.Semaphore(3)

    case_urls = {
        case.id: [url for urls in case.target_urls.values() for url in urls] for case in cases
    }
    unique = sorted({url for urls in case_urls.values() for url in urls})
    print(f"[capture] {len(cases)} cases, {len(unique)} unique URLs", flush=True)

    async def fetch(url: str):
        async with semaphore:
            print(f"[capture] fetching {url[:70]}", flush=True)
            try:
                return await agent._fetch_url(url)
            except Exception as exc:  # noqa: BLE001 - a failed page must not stop the rest
                print(f"[capture] EXCEPTION {url[:70]}: {type(exc).__name__}: {exc}", flush=True)
                raise

    results = await asyncio.gather(*(fetch(url) for url in unique), return_exceptions=True)
    by_url: dict[str, Any] = {}
    for url, result in zip(unique, results, strict=True):
        by_url[url] = result

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    run_dir = results_root / f"capture-{run_id}"

    summary: dict[str, Any] = {"run_id": run_id, "cases": {}, "failed_urls": []}
    for case in cases:
        case_dir = run_dir / "source_snapshots" / f"{case.id}-c1"
        case_dir.mkdir(parents=True, exist_ok=True)
        entries = []
        ok = 0
        for url in case_urls[case.id]:
            result = by_url[url]
            if isinstance(result, BaseException):
                entry = {
                    "url": url,
                    "observed_at": now(),
                    "capture_kind": "collector_fetch_exact_redacted_text",
                    "success": False,
                    "error": f"{type(result).__name__}: {result}",
                    "title": None,
                    "fetch_method": None,
                    "collector_snapshot_hash": None,
                    "content_sha256": None,
                    "content_path": None,
                    "pii_redactions": None,
                }
            else:
                entry = entry_from(result)
                if entry["success"]:
                    (case_dir / entry["content_path"]).write_bytes(
                        result.content.encode("utf-8")
                    )
                    ok += 1
            entries.append(entry)
            if not entry["success"]:
                summary["failed_urls"].append(
                    {"case": case.id, "url": url, "error": entry["error"]}
                )
        (case_dir / "index.json").write_text(
            json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        freeze(run_dir, [f"{case.id}-c1"], bundle_root / f"{case.id}-c1")
        summary["cases"][case.id] = {
            "captured": ok,
            "attempted": len(case_urls[case.id]),
            "bundle": str(bundle_root / f"{case.id}-c1"),
        }
        print(f"[capture] {case.id}: {ok}/{len(case_urls[case.id])} pages OK", flush=True)

    summary["generated_at"] = now()
    (run_dir / "capture_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "benchmark/cases/final_cases.json")
    parser.add_argument("--results-root", type=Path, default=ROOT / "benchmark/results")
    parser.add_argument("--bundle-root", type=Path, default=ROOT / "benchmark/replay_bundles")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env", override=False)
    summary = asyncio.run(capture(args.cases, args.results_root, args.bundle_root))
    failed = summary["failed_urls"]
    print(f"\n[capture] done. failed URLs: {len(failed)}")
    for item in failed:
        print(f"  {item['case']}: {item['url']} -> {item['error']}")


if __name__ == "__main__":
    main()
