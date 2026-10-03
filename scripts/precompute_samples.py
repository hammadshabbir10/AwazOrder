"""Run the real agent pipeline on every sample once and cache the results.

The deployed demo then serves sample orders from app/samples_cache.json with
no API call at all, so they keep working even when every provider is busy.
Resumable: samples already cached with an agent trace are kept, and a sample
that hits the free-tier rate limit is retried after a pause.

    GROQ_API_KEY=... python -m scripts.precompute_samples
"""

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DB_PATH", str(Path(__file__).resolve().parent.parent / "awaz.db"))

from app import config  # noqa: E402,F401  (loads .env)
from app.db import init_db  # noqa: E402
from app.pipeline import parse_text  # noqa: E402

BASE = Path(__file__).resolve().parent.parent / "app"
CACHE = BASE / "samples_cache.json"
ATTEMPTS = 4
PAUSE_S = 35


def complete(draft: dict) -> bool:
    """Every AI agent ran on a model (no fallback, no 'AI busy' skip)."""
    if draft.get("mode") != "ai":
        return False
    for step in draft.get("agents", []):
        if step["key"] in ("router", "extractor", "verifier") and step["status"] == "fallback":
            return False
        if step["key"] == "verifier" and step["summary"].startswith("AI busy"):
            return False
    return True


def main() -> None:
    if not os.environ.get("GROQ_API_KEY"):
        sys.exit("Set GROQ_API_KEY first.")
    init_db()
    samples = json.loads((BASE / "samples.json").read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    for s in samples:
        if s["id"] in cache and cache[s["id"]].get("agents"):
            print(f"{s['id']}: already cached", flush=True)
            continue
        for attempt in range(1, ATTEMPTS + 1):
            draft = parse_text(s["transcript"])
            if complete(draft):
                cache[s["id"]] = draft
                CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
                print(f"{s['id']}: {draft['intent']}, {len(draft['lines'])} lines, agents "
                      f"{[a['name'] + ':' + a['status'] for a in draft['agents']]}", flush=True)
                break
            print(f"{s['id']}: attempt {attempt} hit a busy model, waiting {PAUSE_S}s", flush=True)
            time.sleep(PAUSE_S)
        else:
            sys.exit(f"{s['id']}: still rate-limited after {ATTEMPTS} attempts; run again later.")
        time.sleep(8)
    print("Wrote app/samples_cache.json")


if __name__ == "__main__":
    main()
