"""Order pipeline: transcript -> structured, priced, validated order draft."""

from app import ai
from app.db import get_products, get_shops
from app.parser import match_product, offline_parse
from rapidfuzz import fuzz, process

REVIEW_THRESHOLD = 0.75


def vocabulary_hint(products: list[dict]) -> str:
    """Short brand list passed to Whisper as a prompt to improve brand spelling."""
    brands = sorted({p["name"].split()[0] for p in products})
    return "Order for a distributor. Brands: " + ", ".join(brands)


def _normalise(raw: dict, products: list[dict], transcript: str) -> dict:
    by_sku = {p["sku"]: p for p in products}
    lines = []
    for item in raw.get("lines", []):
        sku = item.get("sku")
        confidence = float(item.get("confidence") or 0.8)
        alternatives = [a for a in item.get("alternatives") or [] if a in by_sku and a != sku]
        if sku not in by_sku:
            # The model invented or misspelled a sku: re-match the spoken words.
            candidates = match_product(item.get("spoken") or "", products)
            if not candidates:
                continue
            sku, score = candidates[0]
            confidence = min(confidence, score)
            alternatives = [s for s, _ in candidates[1:]]
        try:
            quantity = float(item.get("quantity") or 1)
        except (TypeError, ValueError):
            quantity = 1.0
            confidence = min(confidence, 0.5)
        product = by_sku[sku]
        quantity = int(quantity) if quantity.is_integer() else quantity
        lines.append({
            "sku": sku,
            "name": product["name"],
            "unit": product["unit"],
            "spoken": item.get("spoken") or "",
            "quantity": quantity,
            "price": product["price"],
            "line_total": round(product["price"] * quantity),
            "confidence": round(max(0.0, min(confidence, 1.0)), 2),
            "needs_review": confidence < REVIEW_THRESHOLD or bool(alternatives),
            "alternatives": [{"sku": a, "name": by_sku[a]["name"]} for a in alternatives[:3]],
        })

    shop_id = None
    hint = raw.get("shop_hint")
    if hint:
        shops = get_shops()
        found = process.extractOne(hint, {s["id"]: s["name"] for s in shops}, scorer=fuzz.WRatio)
        if found and found[1] >= 70:
            shop_id = found[2]

    payment = raw.get("payment") if raw.get("payment") in ("credit", "cash") else "unknown"
    return {
        "transcript": transcript,
        "lines": lines,
        "unmatched": [u for u in raw.get("unmatched") or [] if u],
        "payment": payment,
        "shop_id": shop_id,
        "total": sum(l["line_total"] for l in lines),
    }


def parse_text(transcript: str, use_ai: bool = True) -> dict:
    """Structured order from text. Falls back to the offline parser if AI fails."""
    products = get_products()
    mode, provider, error = "offline", None, None
    raw = None
    if use_ai:
        try:
            raw, provider = ai.extract_order(transcript, products)
            mode = "ai"
        except ai.AllProvidersFailed as exc:
            error = str(exc)
    if raw is None:
        raw = offline_parse(transcript, products)
    draft = _normalise(raw, products, transcript)
    draft.update({"mode": mode, "provider": provider, "ai_error": error})
    return draft


class NoSpeech(Exception):
    """The recording had no usable speech."""


# What Whisper tends to invent from silence or background noise.
WHISPER_SILENCE = {"thank you", "thanks for watching", "شکریہ", "you", "bye", "subtitles"}


def parse_audio(audio: bytes, filename: str, content_type: str) -> dict:
    products = get_products()
    transcript, asr_provider = ai.transcribe(audio, filename, content_type, vocabulary_hint(products))
    cleaned = transcript.strip(" .۔!?،,").lower()
    if len(cleaned) < 4 or cleaned in WHISPER_SILENCE:
        raise NoSpeech()
    draft = parse_text(transcript)
    draft["asr_provider"] = asr_provider
    return draft


def format_pkr(amount: float) -> str:
    return f"Rs {round(amount):,}"


URDU_UNITS = {"carton": "کارٹن", "tin": "ٹین", "pack": "پیکٹ", "bag": "بیگ", "bori": "بوری", "kg": "کلو", "bottle": "بوتل"}


def spoken_reply(order_id: int, shop_name: str, lines: list[dict], total: int,
                 payment: str, balance: int) -> str:
    """The same confirmation, phrased to be read aloud (no symbols or bullets)."""
    items = "، ".join(
        f"{l['quantity']} {URDU_UNITS.get(l['unit'], l['unit'])} {l['name']}" for l in lines
    )
    if payment == "credit":
        pay = f"یہ رقم آپ کے کھاتے میں لکھ دی گئی ہے، اور کل بقایا {round(balance):,} روپے ہے۔"
    elif payment == "cash":
        pay = "ادائیگی ڈیلیوری پر نقد ہو گی۔"
    else:
        pay = "براہِ کرم بتا دیں کہ ادائیگی نقد ہو گی یا کھاتے میں۔"
    return (
        f"السلام علیکم {shop_name}۔ آپ کا آرڈر نمبر {order_id} کنفرم ہو گیا ہے۔ "
        f"{items}۔ کل رقم {round(total):,} روپے۔ {pay} شکریہ۔"
    )


def whatsapp_reply(order_id: int, shop_name: str, lines: list[dict], total: int,
                   payment: str, balance: int, distributor: str) -> str:
    """Urdu confirmation the order-taker can paste into WhatsApp."""
    items = "\n".join(
        f"• {l['quantity']} {l['unit']} {l['name']} — {format_pkr(l['line_total'])}" for l in lines
    )
    if payment == "credit":
        pay = f"یہ رقم آپ کے کھاتے میں لکھ دی گئی ہے۔ کل بقایا: {format_pkr(balance)}"
    elif payment == "cash":
        pay = "ادائیگی: نقد (ڈیلیوری پر)"
    else:
        pay = "ادائیگی کا طریقہ بتا دیں: نقد یا کھاتہ؟"
    return (
        f"السلام علیکم {shop_name}!\n"
        f"آپ کا آرڈر #{order_id} کنفرم ہو گیا ہے:\n{items}\n"
        f"کل رقم: {format_pkr(total)}\n{pay}\n"
        f"شکریہ — {distributor}"
    )
