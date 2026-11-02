"""Replay serves frozen text only; any gap must fail loudly, never re-fetch."""

import hashlib
import json
from pathlib import Path

import pytest

from agents.collector.agent import CollectorAgent, snapshot_replay_provider
from benchmark.models import BenchmarkCase, RunConfig
from benchmark.replay import SnapshotBundle, SnapshotReplayError, freeze
from benchmark.runner import load_replay_bundles


def _write_task_snapshot(run_dir: Path, task_id: str, captures: dict[str, str]) -> None:
    task_dir = run_dir / "source_snapshots" / task_id
    task_dir.mkdir(parents=True)
    entries = []
    for url, text in captures.items():
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        (task_dir / f"{digest}.txt").write_text(text, encoding="utf-8")
        entries.append(
            {
                "url": url,
                "observed_at": "2026-10-29T10:08:22Z",
                "capture_kind": "collector_fetch_exact_redacted_text",
                "success": True,
                "error": None,
                "title": f"title for {url}",
                "fetch_method": "direct_http_fetch",
                "content_sha256": digest,
                "content_path": f"{digest}.txt",
            }
        )
    (task_dir / "index.json").write_text(json.dumps(entries), encoding="utf-8")


@pytest.fixture()
def frozen_bundle(tmp_path: Path) -> SnapshotBundle:
    run_dir = tmp_path / "run"
    _write_task_snapshot(
        run_dir,
        "case-r1-c1",
        {"https://a.example.com": "A page text", "https://b.example.com": "B page text"},
    )
    return freeze(run_dir, ["case-r1-c1"], tmp_path / "bundle" / "case-c1")


def test_fetch_returns_frozen_text_with_hash(frozen_bundle: SnapshotBundle) -> None:
    result = frozen_bundle.fetch("https://a.example.com")
    assert result.success is True
    assert result.content == "A page text"
    assert result.fetch_method == "snapshot_replay"
    assert result.snapshot_hash


def test_fetch_unknown_url_raises_instead_of_live_fallback(frozen_bundle: SnapshotBundle) -> None:
    with pytest.raises(SnapshotReplayError, match="forbidden"):
        frozen_bundle.fetch("https://missing.example.com")


def test_load_rejects_tampered_content(tmp_path: Path, frozen_bundle: SnapshotBundle) -> None:
    entry = frozen_bundle.entries[0]
    (frozen_bundle.directory / entry["content_path"]).write_text("tampered", encoding="utf-8")
    with pytest.raises(SnapshotReplayError, match="hash mismatch"):
        SnapshotBundle.load(frozen_bundle.directory)


def test_freeze_refuses_conflicting_captures(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    _write_task_snapshot(run_dir, "case-r1-c1", {"https://a.example.com": "version one"})
    _write_task_snapshot(run_dir, "case-r2-c1", {"https://a.example.com": "version two"})
    with pytest.raises(SnapshotReplayError, match="Conflicting"):
        freeze(run_dir, ["case-r1-c1", "case-r2-c1"], tmp_path / "bundle")


async def test_collector_fetch_url_uses_provider_without_network(
    frozen_bundle: SnapshotBundle,
) -> None:
    async def _explode(url):  # any network access means the hook failed
        raise AssertionError(f"network fetch attempted for {url}")

    from agents.collector import agent as collector_agent

    collector_agent.is_allowed_by_robots = _explode
    token = snapshot_replay_provider.set(frozen_bundle.fetch)
    try:
        result = await CollectorAgent()._fetch_url("https://a.example.com")
    finally:
        snapshot_replay_provider.reset(token)
    assert result.success and result.content == "A page text"


def test_load_replay_bundles_pins_target_urls(frozen_bundle: SnapshotBundle) -> None:
    case = BenchmarkCase(id="case", competitors=["Alpha"], required_dimensions=["pricing"])
    config = RunConfig(replay_root=str(frozen_bundle.directory.parent))
    bundles = load_replay_bundles([case], config)
    assert case.target_urls == {"Alpha": sorted(frozen_bundle.urls)}
    assert set(bundles) == {"case-c1"}


def test_load_replay_bundles_missing_bundle_raises(tmp_path: Path) -> None:
    case = BenchmarkCase(id="case", competitors=["Alpha"], required_dimensions=["pricing"])
    config = RunConfig(replay_root=str(tmp_path))
    with pytest.raises(FileNotFoundError, match="case-c1"):
        load_replay_bundles([case], config)
