"""Order pipeline: transcript -> structured, priced, validated order draft."""

import time

from app import ai
from app.db import get_products, get_shops
from app.parser import match_product, offline_parse
from app.seed import URDU_PRODUCT_NAMES, URDU_SHOP_NAMES
from app.urdu import integer_words, quantity_words, rupees_words
from rapidfuzz import fuzz, process

REVIEW_THRESHOLD = 0.75


def vocabulary_hint(products: list[dict]) -> str:
    """Short brand list passed to Whisper as a prompt to improve brand spelling."""
    brands = sorted({p["name"].split()[0] for p in products})
    return "Order for a distributor. Brands: " + ", ".join(brands)


def build_line(by_sku: dict, sku: str, quantity: float, spoken: str = "", confidence: float = 0.9,
               alternatives: list[str] | None = None, review_reason: str | None = None) -> dict:
    """One priced order line. Prices always come from the catalogue, never the model."""
    product = by_sku[sku]
    quantity = float(quantity)
    quantity = int(quantity) if quantity.is_integer() else quantity
    alternatives = [a for a in alternatives or [] if a in by_sku and a != sku]
    return {
        "sku": sku,
        "name": product["name"],
        "unit": product["unit"],
        "spoken": spoken,
        "quantity": quantity,
        "price": product["price"],
        "line_total": round(product["price"] * quantity),
        "confidence": round(max(0.0, min(confidence, 1.0)), 2),
        "needs_review": confidence < REVIEW_THRESHOLD or bool(alternatives) or bool(review_reason),
        "alternatives": [{"sku": a, "name": by_sku[a]["name"]} for a in alternatives[:3]],
        "review_reason": review_reason,
    }


def find_shop(hint: str | None, shops: list[dict], text: str = "") -> int | None:
    """Match a spoken shop name to a shop; falls back to scanning the whole text."""
    # Every shop answers to its English and its Urdu-script name.
    clean = lambda v: v.lower().replace("-", " ")  # "Al-Rehman" == "Al Rehman"
    names = [(s["id"], clean(n)) for s in shops for n in (s["name"], URDU_SHOP_NAMES.get(s["name"], "")) if n]
    if hint:
        # token_set_ratio: distinctive words ("faisal") count, shared ones ("store") do not dominate.
        found = process.extractOne(clean(hint), [n for _, n in names], scorer=fuzz.token_set_ratio)
        if found and found[1] >= 70:
            return names[found[2]][0]
    lowered = clean(text)
    best = max(((fuzz.partial_ratio(n, lowered), sid) for sid, n in names), default=(0, None))
    return best[1] if best[0] >= 88 else None


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
        lines.append(build_line(by_sku, sku, quantity, item.get("spoken") or "", confidence, alternatives))

    shop_id = find_shop(raw.get("shop_hint"), get_shops(), transcript)

    payment = raw.get("payment") if raw.get("payment") in ("credit", "cash") else "unknown"
    return {
        "transcript": transcript,
        "lines": lines,
        "unmatched": [u for u in raw.get("unmatched") or [] if u],
        "payment": payment,
        "shop_id": shop_id,
        "total": sum(l["line_total"] for l in lines),
    }


class NoSpeech(Exception):
    """The recording had no usable speech."""


# What Whisper tends to invent from silence or background noise.
WHISPER_SILENCE = {"thank you", "thanks for watching", "شکریہ", "you", "bye", "subtitles"}


def parse_text(transcript: str, use_ai: bool = True, intent: str | None = None) -> dict:
    """Typed message -> draft, through the agent pipeline (see app/agents.py)."""
    from app import agents
    return agents.run(transcript, use_ai=use_ai, forced_intent=intent)


def parse_audio(audio: bytes, filename: str, content_type: str) -> dict:
    """Voice note -> draft: the Listener agent first, then the same agent pipeline."""
    from app import agents
    return agents.run_audio(audio, filename, content_type)


def format_pkr(amount: float) -> str:
    return f"Rs {round(amount):,}"


URDU_UNITS = {"carton": "کارٹن", "tin": "ٹین", "pack": "پیکٹ", "bag": "بیگ", "bori": "بوری", "kg": "کلو", "bottle": "بوتل"}

# Right-to-left mark: keeps an English product or shop name from dragging
# neighbouring numbers and punctuation to the wrong side of an Urdu line.
RLM = "‏"


def spoken_reply(order_id: int, shop_name: str, lines: list[dict], total: int,
                 payment: str, balance: int) -> str:
    """The confirmation phrased to be read aloud: Urdu script only.

    Every product and shop name is in Urdu and every number is spelled out in
    words, so the voice has nothing to guess (no "Rs", commas, digits or
    English names, which TTS voices misread or improvise around).
    """
    shop = URDU_SHOP_NAMES.get(shop_name, shop_name)
    items = "۔ ".join(
        f"{quantity_words(l['quantity'])} {URDU_UNITS.get(l['unit'], l['unit'])} "
        f"{URDU_PRODUCT_NAMES.get(l['sku'], l['name'])}، {rupees_words(l['line_total'])}"
        for l in lines
    )
    if payment == "credit":
        pay = f"یہ رقم آپ کے کھاتے میں لکھ دی گئی ہے۔ آپ کا کل بقایا {rupees_words(balance)} ہے۔"
    elif payment == "cash":
        pay = "ادائیگی ڈیلیوری پر نقد ہو گی۔"
    else:
        pay = "براہِ کرم بتا دیں کہ ادائیگی نقد ہو گی یا کھاتے میں۔"
    return (
        f"السلام علیکم، {shop}۔ آپ کا آرڈر نمبر {integer_words(order_id)} کنفرم ہو گیا ہے۔ "
        f"{items}۔ کل رقم {rupees_words(total)}۔ {pay} شکریہ۔"
    )


def whatsapp_reply(order_id: int, shop_name: str, lines: list[dict], total: int,
                   payment: str, balance: int, distributor: str) -> str:
    """Urdu confirmation the order-taker can paste into WhatsApp.

    Each line starts and ends with Urdu (unit word, "روپے") so it reads
    correctly right-to-left; English product names stay in the middle.
    """
    items = "\n".join(
        f"• {l['quantity']} {URDU_UNITS.get(l['unit'], l['unit'])} {l['name']}{RLM} — {l['line_total']:,} روپے"
        for l in lines
    )
    if payment == "credit":
        pay = f"یہ رقم آپ کے کھاتے میں لکھ دی گئی ہے۔ کل بقایا: {round(balance):,} روپے"
    elif payment == "cash":
        pay = "ادائیگی: ڈیلیوری پر نقد"
    else:
        pay = "ادائیگی کا طریقہ بتا دیں: نقد یا کھاتہ؟"
    return (
        f"السلام علیکم، {shop_name}{RLM}\n"
        f"آپ کا آرڈر نمبر {order_id} کنفرم ہو گیا ہے:\n{items}\n"
        f"کل رقم: {round(total):,} روپے\n{pay}\n"
        f"شکریہ، {distributor}{RLM}"
    )


def payment_receipt(shop_name: str, amount: int, balance: int, distributor: str) -> tuple[str, str]:
    """(WhatsApp text, spoken text) acknowledging a payment from a shop."""
    text = (
        f"السلام علیکم، {shop_name}{RLM}\n"
        f"آپ کی {amount:,} روپے کی ادائیگی موصول ہو گئی ہے۔ شکریہ!\n"
        f"آپ کا باقی بقایا: {round(balance):,} روپے\n"
        f"{distributor}{RLM}"
    )
    shop = URDU_SHOP_NAMES.get(shop_name, shop_name)
    spoken = (
        f"السلام علیکم، {shop}۔ آپ کی {rupees_words(amount)} کی ادائیگی موصول ہو گئی ہے۔ شکریہ۔ "
        f"آپ کا باقی بقایا {rupees_words(max(balance, 0))} ہے۔"
    )
    return text, spoken


def balance_reply(shop_name: str, balance: int, distributor: str) -> tuple[str, str]:
    """(WhatsApp text, spoken text) answering 'how much do I owe?'."""
    text = (
        f"السلام علیکم، {shop_name}{RLM}\n"
        f"آپ کا موجودہ بقایا: {round(balance):,} روپے\n"
        f"ادائیگی کے لیے رابطہ کریں۔ شکریہ،\n{distributor}{RLM}"
    )
    shop = URDU_SHOP_NAMES.get(shop_name, shop_name)
    spoken = f"السلام علیکم، {shop}۔ آپ کا موجودہ بقایا {rupees_words(max(balance, 0))} ہے۔ شکریہ۔"
    return text, spoken
