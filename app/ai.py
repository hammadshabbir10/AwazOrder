"""Open-model inference with a provider fallback chain.

Primary: Groq (Whisper large-v3 + Qwen 3.8 / gpt-oss-120b). Backup: any OpenAI-compatible
provider serving open models (OpenRouter, Together, Fireworks, a self-hosted
vLLM / Ollama, ...). If both fail, callers fall back to the offline parser.
"""

import json
import os
import time
from dataclasses import dataclass

import httpx

TIMEOUT = httpx.Timeout(45.0, connect=10.0)


@dataclass
class Provider:
    name: str
    base_url: str
    api_key: str
    asr_model: str | None
    llm_models: list[str]


def providers() -> list[Provider]:
    chain = []
    if os.environ.get("GROQ_API_KEY"):
        chain.append(Provider(
            "groq",
            "https://api.groq.com/openai/v1",
            os.environ["GROQ_API_KEY"],
            os.environ.get("GROQ_ASR_MODEL", "whisper-large-v3"),
            # Groq rate-limits each model separately, so a second open model
            # doubles the free-tier headroom before the offline parser kicks in.
            _models(os.environ.get("GROQ_LLM_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-120b")),
        ))
    if os.environ.get("BACKUP_API_KEY") and os.environ.get("BACKUP_BASE_URL"):
        chain.append(Provider(
            "backup",
            os.environ["BACKUP_BASE_URL"].rstrip("/"),
            os.environ["BACKUP_API_KEY"],
            os.environ.get("BACKUP_ASR_MODEL") or None,
            _models(os.environ.get("BACKUP_LLM_MODELS", "")),
        ))
    return chain


def _models(value: str) -> list[str]:
    return [m.strip() for m in value.split(",") if m.strip()]


# Last outcome per provider, surfaced in the UI status badge.
STATUS: dict[str, dict] = {}


def _record(name: str, ok: bool, error: str | None = None) -> None:
    STATUS[name] = {"ok": ok, "error": error, "at": int(time.time())}


class AllProvidersFailed(Exception):
    pass


def transcribe(audio: bytes, filename: str, content_type: str, vocabulary: str) -> tuple[str, str]:
    """Speech-to-text. Returns (transcript, provider name)."""
    errors = []
    for p in providers():
        if not p.asr_model:
            continue
        try:
            resp = httpx.post(
                f"{p.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {p.api_key}"},
                files={"file": (filename, audio, content_type)},
                # The prompt biases Whisper towards catalogue brand names.
                data={"model": p.asr_model, "prompt": vocabulary, "temperature": "0"},
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            text = resp.json().get("text", "").strip()
            _record(p.name, True)
            return text, p.name
        except Exception as exc:  # noqa: BLE001 - any failure moves to the next provider
            _record(p.name, False, _describe(exc))
            errors.append(f"{p.name}: {_describe(exc)}")
    raise AllProvidersFailed("; ".join(errors) or "no speech provider configured")


EXTRACTION_PROMPT = """You turn a Pakistani shopkeeper's order (Urdu, Roman Urdu, Punjabi or English, often informal) into structured JSON.

Catalogue (sku | product | unit | aliases):
{catalogue}

Rules:
- Only use skus from the catalogue. If an item matches nothing, put it in "unmatched".
- quantity is a number. Convert number words ("do"=2, "teen"=3, "dedh"=1.5, "darjan"=12).
- If the item is ambiguous between products, pick the most likely sku, lower "confidence" and list the others in "alternatives".
- payment: "credit" if they ask to add it to their account/khata/udhaar, "cash" if they say cash/naqd, else "unknown".
- shop_hint: the shop name if the speaker mentions it, else null.

Return ONLY this JSON:
{{"lines":[{{"sku":"...","spoken":"words used for this item","quantity":1,"unit":"carton","confidence":0.0,"alternatives":[]}}],
 "unmatched":["..."],"payment":"credit|cash|unknown","shop_hint":null}}"""


def extract_order(transcript: str, products: list[dict]) -> tuple[dict, str]:
    """LLM structured extraction. Returns (parsed json, provider name)."""
    catalogue = "\n".join(
        f"{p['sku']} | {p['name']} | {p['unit']} | {', '.join(p['aliases'])}" for p in products
    )
    errors = []
    for p, model in ((p, m) for p in providers() for m in p.llm_models):
        name = f"{p.name}:{model}"
        try:
            resp = httpx.post(
                f"{p.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {p.api_key}"},
                json={
                    "model": model,
                    "temperature": 0,
                    "response_format": {"type": "json_object"},
                    "messages": [
                        {"role": "system", "content": EXTRACTION_PROMPT.format(catalogue=catalogue)},
                        {"role": "user", "content": transcript},
                    ],
                },
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed.get("lines"), list):
                raise ValueError("model returned no 'lines' array")
            _record(name, True)
            return parsed, name
        except Exception as exc:  # noqa: BLE001
            _record(name, False, _describe(exc))
            errors.append(f"{name}: {_describe(exc)}")
    raise AllProvidersFailed("; ".join(errors) or "no language model configured")


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return "rate limited" if code == 429 else f"HTTP {code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return type(exc).__name__
