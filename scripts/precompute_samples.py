"""Run the real AI pipeline on every sample once and cache the results.

The deployed demo then serves sample orders from app/samples_cache.json with
no API call at all, so they keep working even when every provider is busy.

    GROQ_API_KEY=... python -m scripts.precompute_samples
"""

import json
import time
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DB_PATH", str(Path(__file__).resolve().parent.parent / "awaz.db"))

from app.db import init_db  # noqa: E402
from app.pipeline import parse_text  # noqa: E402

BASE = Path(__file__).resolve().parent.parent / "app"


def main() -> None:
    if not os.environ.get("GROQ_API_KEY"):
        sys.exit("Set GROQ_API_KEY first.")
    init_db()
    samples = json.loads((BASE / "samples.json").read_text(encoding="utf-8"))
    cache = {}
    for s in samples:
        draft = parse_text(s["transcript"])
        if draft["mode"] != "ai":
            sys.exit(f"{s['id']}: AI call failed ({draft['ai_error']}); not caching an offline result.")
        cache[s["id"]] = draft
        time.sleep(3)  # stay under the free-tier per-minute limit
        print(f"{s['id']}: {len(draft['lines'])} lines, total Rs {draft['total']:,}")
    (BASE / "samples_cache.json").write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Wrote app/samples_cache.json")


if __name__ == "__main__":
    main()
