# Awaz Order

AI order desk for Pakistani distributors. Shopkeepers order by WhatsApp voice
note in Urdu, Punjabi or English; Awaz Order transcribes the note, extracts the
items, matches them to the distributor's catalogue, flags anything uncertain for
review, creates the priced order, updates the shop's khata (credit ledger) and
writes an Urdu WhatsApp confirmation.

**Demo login:** `demo@awazorder.pk` / `Demo@1234`

## How it works

| Step | Component | Tool |
| --- | --- | --- |
| Speech-to-text | Urdu / Punjabi / English voice note → text, biased towards catalogue brand names | Whisper large-v3 (open-source) |
| Order extraction | Text → JSON lines (sku, quantity, confidence, alternatives), payment intent, shop hint | Qwen 3.8 27B, then gpt-oss-120b (open-weight) |
| Catalogue matching | Validates every sku; re-matches invented or misspelt items against Urdu / Roman Urdu / English aliases | RapidFuzz |
| Human review | Low-confidence lines are highlighted with "Did you mean…?" suggestions | Web UI |
| Ledger + reply | Credit orders update the khata; Urdu confirmation generated for WhatsApp | FastAPI + SQLite |

### Reliability: the fallback chain

1. **Sample orders** are served from `app/samples_cache.json` (real AI output, pre-computed) with no API call.
2. **Live requests** try each open model on the primary provider (Groq), then an optional backup OpenAI-compatible provider.
3. If every provider is down or rate-limited, an **offline rule-based parser** (Urdu / Roman Urdu number words, units, filler phrases + RapidFuzz) still produces the order from typed text.
4. Per-user rate limit (default 15 live AI calls / hour) and a 30-second audio limit protect the free tier.

## Run locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt      # Windows (use .venv/bin on macOS/Linux)
cp .env.example .env                               # add GROQ_API_KEY (free at console.groq.com)
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. Without an API key the app runs in offline mode.

Re-generate the sample cache after changing samples or models:

```bash
python -m scripts.precompute_samples
```

## Deploy (Render, free)

1. Push this repo to GitHub.
2. Render → **New → Blueprint** → select the repo (uses `render.yaml`).
3. Set `GROQ_API_KEY` when prompted. `SECRET_KEY` is generated automatically.
4. Optional: point a free uptime monitor at `/api/status` every 5 minutes so the free instance does not sleep.

The demo database lives in `/tmp` and is re-seeded on every restart.

Alternative: Hugging Face Spaces (Docker) using the included `Dockerfile` (port 7860).

## Architecture

See [`docs/architecture.mmd`](docs/architecture.mmd) (render at https://mermaid.live).

## Roadmap

- WhatsApp Business API: receive voice notes and send confirmations directly
- Fine-tune Whisper on collected (consented) voice notes for Punjabi and noisy shops
- Embedding search (multilingual) for catalogues with thousands of SKUs
- Reorder prediction and demand forecasting per shop
- Payment reminders and credit scoring from ledger history
