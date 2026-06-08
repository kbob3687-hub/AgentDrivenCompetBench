"""Full 3-competitor pipeline test with auto HITL pass."""

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, "src")

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")


async def main():
    from datetime import datetime

    from api.events import EventType, event_bus
    from api.runner import _task_traces, build_sse_graph

    competitors = ["Notion"]
    results = {}

    import api.runner as runner

    original_publish = runner._publish

    async def auto_publish(tid, etype, data):
        await original_publish(tid, etype, data)
        if etype == EventType.HITL_PAUSE:
            runner._hitl_decisions[tid] = "force_pass"
            gate = runner._hitl_gates.get(tid)
            if gate:
                gate.set()

    runner._publish = auto_publish

    for name in competitors:
        task_id = str(uuid.uuid4())
        event_bus.create_task(task_id)
        _task_traces[task_id] = []

        print(f"\n{'=' * 60}")
        print(f"Starting: {name} (task: {task_id[:8]}...)")
        print(f"{'=' * 60}")

        initial_state = {
            "competitor_name": name,
            "collect_scope": ["pricing", "features"],
            "target_urls": [],
            "expected_dimensions": ["pricing", "features", "integrations"],
            "industry": "saas",
            "industry_fields": [],
            "discovery_strategy": "official_only",
            "trusted_domains": [],
            "iteration": 1,
            "max_iterations": 3,
            "feedback_history": [],
            "missing_dimensions": [],
            "trace_id": task_id,
            "started_at": datetime.now().isoformat(),
            "final_status": "running",
            "agent_traces": [],
        }

        start = time.time()
        app = build_sse_graph()
        config = {"recursion_limit": 18}

        try:
            final_state = await app.ainvoke(initial_state, config=config)
            elapsed = time.time() - start
            traces = _task_traces.pop(task_id, [])
            final_state["agent_traces"] = traces

            qa_score = final_state.get("qa_score", 0)
            verdict = final_state.get("qa_verdict", "unknown")
            iteration = final_state.get("iteration", 1) - 1
            report_len = len(final_state.get("report_markdown", ""))
            feedback = final_state.get("feedback_history", [])
            claims = final_state.get("claims", [])
            profile = final_state.get("profile", {})
            error = final_state.get("error", "")

            print(f"  Completed in {elapsed:.1f}s")
            print(f"  Claims collected: {len(claims)}")
            print(f"  Profile keys: {list(profile.keys())[:8] if profile else 'EMPTY'}")
            print(f"  Report length: {report_len} chars")
            print(f"  Error field: {error[:100] if error else 'none'}")
            print(f"  QA: verdict={verdict}, score={qa_score:.2f}, iterations={iteration}")

            print(f"  Completed in {elapsed:.1f}s")
            print(f"  QA: verdict={verdict}, score={qa_score:.2f}, iterations={iteration}")
            print(f"  Report: {report_len} chars")
            print(f"  Traces: {len(traces)} agent calls")
            for t in traces:
                print(
                    f"    [{t['agent']}] iter={t['iteration']} {t['duration_ms']}ms | {t.get('output_preview', '')[:80]}"
                )
            print(f"  Feedback history: {len(feedback)} rounds")
            for fb in feedback:
                print(f"    Round {fb['iteration']}: {fb['verdict']} (score={fb['score']:.2f})")

            results[name] = {
                "qa_score": qa_score,
                "verdict": verdict,
                "iterations": iteration,
                "report_length": report_len,
                "traces": len(traces),
                "elapsed_s": round(elapsed, 1),
            }
        except Exception as e:
            elapsed = time.time() - start
            print(f"  FAILED after {elapsed:.1f}s: {e}")
            import traceback

            traceback.print_exc()
            results[name] = {"error": str(e)}

    runner._publish = original_publish

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"{'=' * 60}")
    for name, r in results.items():
        if "error" in r:
            print(f"  {name}: FAILED - {r['error'][:100]}")
        else:
            print(
                f"  {name}: score={r['qa_score']:.2f}, verdict={r['verdict']}, "
                f"{r['iterations']} iters, {r['report_length']} chars, {r['elapsed_s']}s"
            )


if __name__ == "__main__":
    asyncio.run(main())
