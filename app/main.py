"""Awaz Order: FastAPI backend that also serves the web app."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import ai, pipeline
from app.db import connect, get_products, get_shops, init_db, now, verify_password

BASE = Path(__file__).parent
SECRET_KEY = os.environ.get("SECRET_KEY") or secrets.token_hex(32)
SESSION_HOURS = 12
MAX_AUDIO_BYTES = 3 * 1024 * 1024  # ~30s voice note
LIVE_CALLS_PER_HOUR = int(os.environ.get("LIVE_CALLS_PER_HOUR", "15"))

app = FastAPI(title="Awaz Order", docs_url="/api/docs", redoc_url=None)


@app.on_event("startup")
def _startup() -> None:
    init_db()


# ---------------------------------------------------------------- auth

def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_session(user_id: int) -> str:
    payload = f"{user_id}:{int(time.time()) + SESSION_HOURS * 3600}"
    return base64.urlsafe_b64encode(f"{payload}:{_sign(payload)}".encode()).decode()


def current_user(request: Request) -> dict:
    token = request.cookies.get("session")
    try:
        user_id, expires, sig = base64.urlsafe_b64decode(token.encode()).decode().split(":")
        if not hmac.compare_digest(sig, _sign(f"{user_id}:{expires}")) or int(expires) < time.time():
            raise ValueError
    except Exception:
        raise HTTPException(401, "Please log in.")
    with connect() as conn:
        row = conn.execute("SELECT id, email, name FROM users WHERE id = ?", (int(user_id),)).fetchone()
    if not row:
        raise HTTPException(401, "Please log in.")
    return dict(row)


class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/login")
def login(body: LoginIn, response: Response):
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (body.email.strip().lower(),)).fetchone()
    if not row or not verify_password(body.password, row["password_hash"]):
        raise HTTPException(401, "Wrong email or password.")
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


def check_rate(user_id: int) -> None:
    window = _calls[user_id]
    cutoff = time.time() - 3600
    while window and window[0] < cutoff:
        window.popleft()
    if len(window) >= LIVE_CALLS_PER_HOUR:
        raise HTTPException(429, "Live AI limit reached for this hour. Try a sample order or type the order instead.")
    window.append(time.time())


# ---------------------------------------------------------------- data

@app.get("/api/catalogue")
def catalogue(user: dict = Depends(current_user)):
    return get_products()


@app.get("/api/shops")
def shops(user: dict = Depends(current_user)):
    return get_shops()


@app.get("/api/status")
def status():
    configured = [p.name for p in ai.providers()]
    return {"providers": configured, "last": ai.STATUS, "offline_fallback": True}


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
        return {**cached, "mode": "cached"}
    # No cache yet: the offline parser keeps samples free of any API dependency.
    draft = pipeline.parse_text(sample["transcript"], use_ai=False)
    return {**draft, "mode": "offline"}


# ---------------------------------------------------------------- live parsing

class TextIn(BaseModel):
    text: str = Field(min_length=3, max_length=1500)


@app.post("/api/parse/text")
def parse_text(body: TextIn, user: dict = Depends(current_user)):
    use_ai = bool(ai.providers())
    if use_ai:
        try:
            check_rate(user["id"])
        except HTTPException:
            use_ai = False  # over the limit: still parse, just offline
    return pipeline.parse_text(body.text, use_ai=use_ai)


@app.post("/api/parse/audio")
async def parse_audio(file: UploadFile = File(...), user: dict = Depends(current_user)):
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty recording.")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Voice note is too long. Please keep it under 30 seconds.")
    check_rate(user["id"])
    try:
        return pipeline.parse_audio(audio, file.filename or "voice.webm", file.content_type or "audio/webm")
    except ai.AllProvidersFailed as exc:
        return JSONResponse(status_code=503, content={
            "detail": "Speech recognition is unavailable right now. Please type the order instead — it will still be processed.",
            "reason": str(exc),
        })


# ---------------------------------------------------------------- orders and ledger

class LineIn(BaseModel):
    sku: str
    quantity: float = Field(gt=0, le=10000)
    spoken: str = ""


class OrderIn(BaseModel):
    shop_id: int
    payment: str = Field(pattern="^(credit|cash|unknown)$")
    transcript: str = ""
    source: str = "voice"
    lines: list[LineIn] = Field(min_length=1, max_length=50)


@app.post("/api/orders")
def create_order(body: OrderIn, user: dict = Depends(current_user)):
    by_sku = {p["sku"]: p for p in get_products()}
    shop = next((s for s in get_shops() if s["id"] == body.shop_id), None)
    if not shop:
        raise HTTPException(400, "Unknown shop.")
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
            "INSERT INTO orders (shop_id, created_at, transcript, payment, total, source, lines_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (shop["id"], now(), body.transcript, body.payment, total, body.source, json.dumps(lines)),
        )
        order_id = cur.lastrowid
        if body.payment == "credit":
            conn.execute(
                "INSERT INTO ledger (shop_id, created_at, kind, amount, note, order_id) VALUES (?, ?, 'credit_order', ?, ?, ?)",
                (shop["id"], now(), total, f"Order #{order_id}", order_id),
            )
        balance = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM ledger WHERE shop_id = ?", (shop["id"],)).fetchone()[0]

    reply = pipeline.whatsapp_reply(order_id, shop["name"], lines, total, body.payment, balance, user["name"])
    return {"id": order_id, "total": total, "balance": balance, "reply": reply, "shop": shop["name"], "phone": shop["phone"]}


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
        top = conn.execute(
            """SELECT s.name, COUNT(o.id) AS orders, COALESCE(SUM(o.total), 0) AS value
               FROM orders o JOIN shops s ON s.id = o.shop_id GROUP BY s.id ORDER BY value DESC LIMIT 5"""
        ).fetchall()
    return {"orders_today": orders_today[0], "value_today": orders_today[1],
            "outstanding": outstanding, "top_shops": [dict(r) for r in top]}


# ---------------------------------------------------------------- web app

app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")
