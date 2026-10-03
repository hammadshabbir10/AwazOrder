"""Open-model inference with a provider fallback chain, plus optional TTS.

Primary: Groq (Whisper large-v3 / turbo + Qwen 3.8 / gpt-oss-120b). Backup: any
OpenAI-compatible provider serving open models (OpenRouter, Together, a
self-hosted vLLM / Ollama, ...). If every provider fails, callers fall back to
the offline parser. ElevenLabs is optional and only reads the Urdu reply aloud.
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
    asr_models: list[str]
    llm_models: list[str]


def _models(value: str) -> list[str]:
    return [m.strip() for m in value.split(",") if m.strip()]


def providers() -> list[Provider]:
    chain = []
    if os.environ.get("GROQ_API_KEY"):
        chain.append(Provider(
            "groq",
            "https://api.groq.com/openai/v1",
            os.environ["GROQ_API_KEY"],
            # Groq rate-limits each model separately, so a second model of each
            # kind roughly doubles the free-tier headroom.
            _models(os.environ.get("GROQ_ASR_MODELS", "whisper-large-v3,whisper-large-v3-turbo")),
            _models(os.environ.get("GROQ_LLM_MODELS", "qwen/qwen3.8-27b,openai/gpt-oss-120b")),
        ))
    if os.environ.get("BACKUP_API_KEY") and os.environ.get("BACKUP_BASE_URL"):
        chain.append(Provider(
            "backup",
            os.environ["BACKUP_BASE_URL"].rstrip("/"),
            os.environ["BACKUP_API_KEY"],
            _models(os.environ.get("BACKUP_ASR_MODELS", "")),
            _models(os.environ.get("BACKUP_LLM_MODELS", "")),
        ))
    return chain


# Last outcome per provider/model, surfaced in the UI status badge.
STATUS: dict[str, dict] = {}


def _record(name: str, ok: bool, error: str | None = None) -> None:
    STATUS[name] = {"ok": ok, "error": error, "at": int(time.time())}


class AllProvidersFailed(Exception):
    pass


def transcribe(audio: bytes, filename: str, content_type: str, vocabulary: str) -> tuple[str, str]:
    """Speech-to-text. Returns (transcript, 'provider:model')."""
    language = os.environ.get("GROQ_ASR_LANGUAGE", "ur")
    errors = []
    for p, model in ((p, m) for p in providers() for m in p.asr_models):
        name = f"{p.name}:{model}"
        data = {"model": model, "prompt": vocabulary, "temperature": "0"}
        # Without a language hint Whisper often writes Urdu speech in Hindi
        # (Devanagari) script; "ur" keeps transcripts in Urdu script.
        if language:
            data["language"] = language
        try:
            resp = httpx.post(
                f"{p.base_url}/audio/transcriptions",
                headers={"Authorization": f"Bearer {p.api_key}"},
                files={"file": (filename, audio, content_type)},
                data=data,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            text = resp.json().get("text", "").strip()
            _record(name, True)
            return text, name
        except Exception as exc:  # noqa: BLE001 - any failure moves to the next model
            _record(name, False, _describe(exc))
            errors.append(f"{name}: {_describe(exc)}")
    raise AllProvidersFailed("; ".join(errors) or "no speech provider configured")


EXTRACTION_PROMPT = """You turn a Pakistani shopkeeper's spoken order into structured JSON.
The text is a voice-note transcript or a typed message in Urdu script, Roman Urdu, Punjabi, Hindi script or English, usually informal and mixed.

Catalogue (sku | product | unit | aliases):
{catalogue}

Rules:
- Only use skus from the catalogue. Anything ordered that matches no product goes in "unmatched" (in the speaker's words).
- quantity must be a number. Convert number words in any language, e.g.
  ek/aik=1, do=2, teen=3, char=4, panch/panj=5, che/chhe=6, saat/satt=7, aath/atth=8, nau=9, das=10, barah=12, bees=20, pachas=50,
  adha=0.5, dedh=1.5, dhai=2.5, darjan=12, and Urdu words (ایک، دو، تین، چار، پانچ، چھ، سات، آٹھ، نو، دس).
- If the speaker corrects themselves ("do carton... nahi nahi, teen kar dein"), use the FINAL quantity or item only.
- Repeated mentions of the same product are one line with the summed quantity.
- If a word could mean several products (e.g. "masala", "chawal", "sabun", "oil"), pick the most likely sku, set confidence below 0.7 and list the other candidate skus in "alternatives".
- confidence is 0.0-1.0: how sure you are of BOTH the product and the quantity.
- payment: "credit" if they ask to add it to their account/khata/udhaar/hisaab, "cash" if they say cash/naqd, else "unknown".
- shop_hint: the shop or business name if the speaker says it, else null.
- Greetings, small talk and delivery instructions are not items.

Return ONLY this JSON:
{{"lines":[{{"sku":"...","spoken":"exact words used for this item","quantity":1,"unit":"carton","confidence":0.0,"alternatives":[]}}],
 "unmatched":["..."],"payment":"credit|cash|unknown","shop_hint":null}}"""


def extract_order(transcript: str, products: list[dict]) -> tuple[dict, str]:
    """LLM structured extraction. Returns (parsed json, 'provider:model')."""
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


# ---------------------------------------------------------------- text-to-speech (optional)

def tts_enabled() -> bool:
    return bool(os.environ.get("ELEVENLABS_API_KEY"))


def speak(text: str) -> bytes:
    """Urdu speech via ElevenLabs. Tries each configured model in order."""
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        raise AllProvidersFailed("ELEVENLABS_API_KEY is not set")
    # Default voice is a premade male voice; any voice id from your ElevenLabs
    # library works. eleven_v3 covers Urdu; multilingual v2 is the fallback.
    voice = os.environ.get("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")
    errors = []
    for model in _models(os.environ.get("ELEVENLABS_MODELS", "eleven_v3,eleven_multilingual_v2")):
        name = f"elevenlabs:{model}"
        body = {"text": text, "model_id": model}
        if model == "eleven_v3":
            # Pin the language and use the most stable setting: v3 is otherwise
            # expressive enough to paraphrase, and an order must be read verbatim.
            body.update({"language_code": "ur", "voice_settings": {"stability": 1.0}})
        try:
            resp = httpx.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": key, "Accept": "audio/mpeg"},
                json=body,
                timeout=TIMEOUT,
            )
            resp.raise_for_status()
            _record(name, True)
            return resp.content
        except Exception as exc:  # noqa: BLE001
            _record(name, False, _describe(exc))
            errors.append(f"{name}: {_describe(exc)}")
    raise AllProvidersFailed("; ".join(errors))


def _describe(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        if code == 429:
            return "rate limited"
        if code in (401, 403):
            return f"HTTP {code} (check the API key)"
        return f"HTTP {code}"
    if isinstance(exc, httpx.TimeoutException):
        return "timeout"
    return type(exc).__name__
