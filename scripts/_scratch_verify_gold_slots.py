"""One-off verifier for formal_gold_slots.draft.json — run, check, delete."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "benchmark" / "gold" / "formal_gold_slots.draft.json"


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def keyword_pattern(kw: str) -> re.Pattern:
    if " " in kw or "[" in kw:
        return re.compile(kw, re.IGNORECASE)
    return re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE)


def main() -> int:
    draft = json.loads(DRAFT.read_text("utf-8"))
    failures = 0
    total = 0
    for case_id, case in draft["cases"].items():
        bundle = ROOT / case["snapshot_bundle"]
        index = json.loads((bundle / "index.json").read_text("utf-8"))
        entries = {e["content_sha256"]: e for e in index["entries"]}
        texts = {
            sha: (bundle / e["content_path"]).read_text("utf-8", errors="replace")
            for sha, e in entries.items()
        }
        for slot in case["slots"]:
            total += 1
            problems = []
            if "quote" in slot:
                sha = slot["content_sha256"]
                if sha not in entries:
                    problems.append(f"sha not in {case_id} index.json")
                elif entries[sha]["url"] != slot["url"]:
                    problems.append(f"url mismatch: index={entries[sha]['url']}")
                elif norm(slot["quote"]) not in norm(texts[sha]):
                    problems.append("quote not found verbatim (whitespace-normalized)")
            else:
                for kw in slot["missing_keywords"]:
                    pat = keyword_pattern(kw["keyword"])
                    hits = sum(len(pat.findall(t)) for t in texts.values())
                    if hits != kw["hits_expected"]:
                        problems.append(
                            f"keyword '{kw['keyword']}' expected {kw['hits_expected']}, got {hits}"
                        )
            status = "PASS" if not problems else "FAIL"
            if problems:
                failures += 1
            print(f"[{status}] {slot['slot_id']}")
            for p in problems:
                print(f"       - {p}")
    print(f"\n{total - failures}/{total} slots verified")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
