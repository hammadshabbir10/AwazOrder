"""Awaz Order: FastAPI backend that also serves the website and web app."""

from app import config  # noqa: F401  (loads .env before anything reads the environment)

import base64
import hashlib
import hmac
import json
import os
import secrets
import tempfile
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import ai, pipeline
from app.db import connect, get_products, get_shops, init_db, now, verify_password

BASE = Path(__file__).parent
STATIC = BASE / "static"
AUDIO_DIR = Path(os.environ.get("AUDIO_DIR", Path(tempfile.gettempdir()) / "awaz-audio"))
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
SESSION_HOURS = 12
MAX_AUDIO_BYTES = 3 * 1024 * 1024  # ~30 s voice note
MIN_AUDIO_BYTES = 2 * 1024         # anything smaller is an empty or broken recording
MAX_AUDIO_SECONDS = 31
AUDIO_TYPES = {
    ".webm": "audio/webm", ".ogg": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4",
    ".mp4": "audio/mp4", ".mp3": "audio/mpeg", ".mpeg": "audio/mpeg", ".mpga": "audio/mpeg",
    ".wav": "audio/wav", ".flac": "audio/flac",
}
LIVE_CALLS_PER_HOUR = int(os.environ.get("LIVE_CALLS_PER_HOUR", "20"))

app = FastAPI(title="Awaz Order", docs_url="/api/docs", redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    init_db()


# ---------------------------------------------------------------- auth

def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(user_id: int) -> str:
    payload = f"{user_id}:{int(time.time()) + SESSION_HOURS * 3600}"
    return base64.urlsafe_b64encode(f"{payload}:{_sign(payload)}".encode()).decode()


def user_from_request(request: Request) -> dict | None:
    token = request.cookies.get("session")
    if not token:
        return None
    try:
        user_id, expires, sig = base64.urlsafe_b64decode(token.encode()).decode().split(":")
        if not hmac.compare_digest(sig, _sign(f"{user_id}:{expires}")) or int(expires) < time.time():
            return None
    except Exception:
        return None
    with connect() as conn:
        row = conn.execute("SELECT id, email, name FROM users WHERE id = ?", (int(user_id),)).fetchone()
    return dict(row) if row else None


def current_user(request: Request) -> dict:
    user = user_from_request(request)
    if not user:
        raise HTTPException(401, "Please sign in.")
    return user


class LoginIn(BaseModel):
    email: str = Field(max_length=200)
    password: str = Field(max_length=200)


@app.post("/api/login")
def login(body: LoginIn, response: Response):
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (body.email.strip().lower(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "That email and password don't match. Try the demo account below.")
    response.set_cookie("session", make_session(row["id"]), httponly=True, samesite="lax",
                        max_age=SESSION_HOURS * 3600, secure=os.environ.get("COOKIE_SECURE") == "1")
    return {"name": row["name"], "email": row["email"]}


@app.post("/api/logout")
def logout(response: Response):
    response.delete_cookie("session")
    return {"ok": True}


@app.get("/api/me")
def me(user: dict = Depends(current_user)):
    return user


# ---------------------------------------------------------------- rate limit (live AI calls only)

_calls: dict[int, deque] = defaultdict(deque)


def within_rate(user_id: int) -> bool:
    window = _calls[user_id]
    cutoff = time.time() - 3600
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= LIVE_CALLS_PER_HOUR:
        return False
    window.append(time.time())
    return True


# ---------------------------------------------------------------- data

@app.get("/api/catalogue")
def catalogue(user: dict = Depends(current_user)):
    return get_products()


@app.get("/api/shops")
def shops(user: dict = Depends(current_user)):
    return get_shops()


@app.get("/api/status")
def status():
    return {
        "providers": [p.name for p in ai.providers()],
        "tts": "elevenlabs" if ai.tts_enabled() else None,
        "last": ai.STATUS,
        "offline_fallback": True,
    }


# ---------------------------------------------------------------- samples (cached, no API calls)

SAMPLES = json.loads((BASE / "samples.json").read_text(encoding="utf-8"))
CACHE_FILE = BASE / "samples_cache.json"


def _sample_cache() -> dict:
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    return {}


@app.get("/api/samples")
def samples(user: dict = Depends(current_user)):
    return [{k: s[k] for k in ("id", "title", "shop", "transcript")} for s in SAMPLES]


@app.post("/api/samples/{sample_id}/parse")
def parse_sample(sample_id: str, user: dict = Depends(current_user)):
    sample = next((s for s in SAMPLES if s["id"] == sample_id), None)
    if not sample:
        raise HTTPException(404, "Unknown sample.")
    cached = _sample_cache().get(sample_id)
    if cached:
        return {**cached, "mode": "cached", "note_id": None}
    # No cache yet: the offline parser keeps samples free of any API dependency.
    return {**pipeline.parse_text(sample["transcript"], use_ai=False), "note_id": None}


# ---------------------------------------------------------------- notes: every real voice note / typed order

def _save_note(user_id: int, kind: str, draft: dict, audio_path: str | None = None,
               duration: float | None = None) -> int:
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO notes (user_id, created_at, kind, transcript, audio_path, duration, draft_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, now(), kind, draft["transcript"], audio_path, duration, json.dumps(draft, ensure_ascii=False)),
        )
        return cur.lastrowid


@app.get("/api/notes")
def list_notes(user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE user_id = ? ORDER BY id DESC LIMIT 30", (user["id"],)
        ).fetchall()
    out = []
    for r in rows:
        draft = json.loads(r["draft_json"])
        out.append({
            "id": r["id"], "created_at": r["created_at"], "kind": r["kind"],
            "transcript": r["transcript"], "duration": r["duration"],
            "has_audio": bool(r["audio_path"]), "order_id": r["order_id"],
            "items": len(draft.get("lines", [])), "total": draft.get("total", 0),
            "mode": draft.get("mode"),
        })
    return out


def _own_note(note_id: int, user: dict):
    with connect() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id = ? AND user_id = ?", (note_id, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "Voice note not found.")
    return row


@app.get("/api/notes/{note_id}")
def get_note(note_id: int, user: dict = Depends(current_user)):
    row = _own_note(note_id, user)
    return {**json.loads(row["draft_json"]), "note_id": row["id"], "reopened": True}


@app.get("/api/notes/{note_id}/audio")
def note_audio(note_id: int, user: dict = Depends(current_user)):
    row = _own_note(note_id, user)
    path = row["audio_path"] and Path(row["audio_path"])
    if not path or not path.exists():
        raise HTTPException(404, "Audio is no longer available (the demo server was restarted).")
    return FileResponse(path, media_type=AUDIO_TYPES.get(path.suffix, "audio/webm"))


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user: dict = Depends(current_user)):
    row = _own_note(note_id, user)
    if row["audio_path"]:
        Path(row["audio_path"]).unlink(missing_ok=True)
    with connect() as conn:
        conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    return {"ok": True}


# ---------------------------------------------------------------- live parsing

class TextIn(BaseModel):
    text: str = Field(min_length=3, max_length=1500)


@app.post("/api/parse/text")
def parse_text(body: TextIn, user: dict = Depends(current_user)):
    # Over the hourly limit, a typed order is still parsed, just offline.
    use_ai = bool(ai.providers()) and within_rate(user["id"])
    draft = pipeline.parse_text(body.text.strip(), use_ai=use_ai)
    draft["note_id"] = _save_note(user["id"], "text", draft)
    return draft


@app.post("/api/parse/audio")
async def parse_audio(
    file: UploadFile = File(...),
    duration: float | None = Form(default=None),
    user: dict = Depends(current_user),
):
    name = file.filename or "voice-note.webm"
    suffix = Path(name).suffix.lower() or ".webm"
    content_type = (file.content_type or "").split(";")[0]
    if suffix not in AUDIO_TYPES and not content_type.startswith("audio/"):
        raise HTTPException(415, "That file isn't a supported audio format. Use mp3, m4a, ogg/opus, wav or webm.")
    if suffix not in AUDIO_TYPES:
        suffix = ".webm"
    audio = await file.read()
    if len(audio) < MIN_AUDIO_BYTES:
        raise HTTPException(422, "The recording is empty or too short. Hold the button and say the full order.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "The voice note is too long. Please keep it under 30 seconds.")
    if duration is not None and duration > MAX_AUDIO_SECONDS:
        raise HTTPException(413, "The voice note is longer than 30 seconds. Please trim it or record again.")
    if not ai.providers():
        raise HTTPException(503, "Voice processing needs an AI key, which isn't configured. Type the order instead.")
    if not within_rate(user["id"]):
        raise HTTPException(429, "You've reached this hour's limit for live voice notes. Type the order or try a sample.")

    # Whisper accepts .ogg but not the .opus extension WhatsApp uses.
    send_suffix = ".ogg" if suffix == ".opus" else suffix
    try:
        draft = pipeline.parse_audio(audio, f"voice-note{send_suffix}", AUDIO_TYPES[suffix])
    except pipeline.NoSpeech:
        raise HTTPException(422, "We couldn't hear an order in that recording. Speak a little closer to the mic and try again.")
    except ai.AllProvidersFailed as exc:
        return JSONResponse(status_code=503, content={
            "detail": "Speech recognition is busy right now. Please type the order instead; it will still be processed.",
            "reason": str(exc),
        })

    audio_path = AUDIO_DIR / f"note-{user['id']}-{int(time.time() * 1000)}{suffix}"
    audio_path.write_bytes(audio)
    draft["note_id"] = _save_note(user["id"], "voice", draft, str(audio_path), duration)
    return draft


# ---------------------------------------------------------------- orders and ledger

class LineIn(BaseModel):
    sku: str
    quantity: float = Field(gt=0, le=10000)
    spoken: str = ""


class OrderIn(BaseModel):
    shop_id: int
    payment: str = Field(pattern="^(credit|cash|unknown)$")
    transcript: str = Field(default="", max_length=2000)
    source: str = Field(default="voice", pattern="^(voice|text|sample)$")
    note_id: int | None = None
    lines: list[LineIn] = Field(min_length=1, max_length=50)


@app.post("/api/orders")
def create_order(body: OrderIn, user: dict = Depends(current_user)):
    by_sku = {p["sku"]: p for p in get_products()}
    shop = next((s for s in get_shops() if s["id"] == body.shop_id), None)
    if not shop:
        raise HTTPException(400, "Choose a shop for this order.")
    lines = []
    for l in body.lines:
        p = by_sku.get(l.sku)
        if not p:
            raise HTTPException(400, f"Unknown product {l.sku}.")
        qty = int(l.quantity) if float(l.quantity).is_integer() else l.quantity
        lines.append({"sku": p["sku"], "name": p["name"], "unit": p["unit"], "quantity": qty,
                      "price": p["price"], "line_total": round(p["price"] * l.quantity)})
    total = sum(l["line_total"] for l in lines)

    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO orders (shop_id, created_at, transcript, payment, total, source, lines_json, note_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (shop["id"], now(), body.transcript, body.payment, total, body.source, json.dumps(lines), body.note_id),
        )
        order_id = cur.lastrowid
        if body.payment == "credit":
            conn.execute(
                "INSERT INTO ledger (shop_id, created_at, kind, amount, note, order_id) VALUES (?, ?, 'credit_order', ?, ?, ?)",
                (shop["id"], now(), total, f"Order #{order_id}", order_id),
            )
        balance = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM ledger WHERE shop_id = ?", (shop["id"],)).fetchone()[0]
        reply = pipeline.whatsapp_reply(order_id, shop["name"], lines, total, body.payment, balance, user["name"])
        spoken = pipeline.spoken_reply(order_id, shop["name"], lines, total, body.payment, balance)
        conn.execute("UPDATE orders SET reply = ?, spoken = ? WHERE id = ?", (reply, spoken, order_id))
        if body.note_id:
            conn.execute("UPDATE notes SET order_id = ? WHERE id = ? AND user_id = ?", (order_id, body.note_id, user["id"]))

    return {"id": order_id, "total": total, "balance": balance, "reply": reply,
            "shop": shop["name"], "phone": shop["phone"], "tts": ai.tts_enabled()}


@app.get("/api/orders/{order_id}/speech")
def order_speech(order_id: int, user: dict = Depends(current_user)):
    """The Urdu confirmation read aloud by ElevenLabs. Cached per order."""
    if not ai.tts_enabled():
        raise HTTPException(501, "Urdu voice needs an ElevenLabs API key (ELEVENLABS_API_KEY).")
    cached = AUDIO_DIR / f"reply-{order_id}.mp3"
    if not cached.exists():
        with connect() as conn:
            row = conn.execute("SELECT spoken FROM orders WHERE id = ?", (order_id,)).fetchone()
        if not row or not row["spoken"]:
            raise HTTPException(404, "Order not found.")
        try:
            cached.write_bytes(ai.speak(row["spoken"]))
        except ai.AllProvidersFailed as exc:
            raise HTTPException(503, f"The voice service is unavailable right now ({exc}).")
    return FileResponse(cached, media_type="audio/mpeg")


@app.get("/api/orders")
def list_orders(user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute(
            """SELECT o.*, s.name AS shop FROM orders o JOIN shops s ON s.id = o.shop_id
               ORDER BY o.id DESC LIMIT 100"""
        ).fetchall()
    return [{**dict(r), "lines": json.loads(r["lines_json"])} for r in rows]


@app.get("/api/shops/{shop_id}/ledger")
def shop_ledger(shop_id: int, user: dict = Depends(current_user)):
    with connect() as conn:
        rows = conn.execute("SELECT * FROM ledger WHERE shop_id = ? ORDER BY id DESC", (shop_id,)).fetchall()
    return [dict(r) for r in rows]


class PaymentIn(BaseModel):
    amount: int = Field(gt=0, le=100_000_000)
    note: str = Field(default="Payment received", max_length=200)


@app.post("/api/shops/{shop_id}/payments")
def record_payment(shop_id: int, body: PaymentIn, user: dict = Depends(current_user)):
    if not any(s["id"] == shop_id for s in get_shops()):
        raise HTTPException(404, "Unknown shop.")
    with connect() as conn:
        conn.execute(
            "INSERT INTO ledger (shop_id, created_at, kind, amount, note) VALUES (?, ?, 'payment', ?, ?)",
            (shop_id, now(), -body.amount, body.note),
        )
    return {"ok": True}


@app.get("/api/dashboard")
def dashboard(user: dict = Depends(current_user)):
    with connect() as conn:
        today = now()[:10]
        orders_today = conn.execute("SELECT COUNT(*), COALESCE(SUM(total), 0) FROM orders WHERE substr(created_at, 1, 10) = ?", (today,)).fetchone()
        outstanding = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM ledger").fetchone()[0]
        notes = conn.execute("SELECT COUNT(*) FROM notes WHERE user_id = ?", (user["id"],)).fetchone()[0]
    return {"orders_today": orders_today[0], "value_today": orders_today[1],
            "outstanding": outstanding, "voice_notes": notes}


# ---------------------------------------------------------------- website pages

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/")
def landing():
    return FileResponse(STATIC / "index.html")


@app.get("/login")
def login_page(request: Request):
    if user_from_request(request):
        return RedirectResponse("/app", status_code=303)
    return FileResponse(STATIC / "login.html")


@app.get("/app")
def app_page(request: Request):
    if not user_from_request(request):
        return RedirectResponse("/login", status_code=303)
    return FileResponse(STATIC / "app.html")
