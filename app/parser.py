"""Catalogue matching and the offline (no-API) order parser.

The offline parser is the last line of the fallback chain: if every AI provider
is down or rate-limited, a typed or sample order still becomes a structured
order. It is rule-based (number words, units, filler words) plus RapidFuzz
matching against the catalogue's Roman Urdu / Urdu / English aliases.
"""

import re

from rapidfuzz import fuzz, process

URDU_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

NUMBER_WORDS = {
    # Roman Urdu
    "ek": 1, "aik": 1, "ik": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4,
    "panch": 5, "paanch": 5, "che": 6, "chay": 6, "chhe": 6, "chey": 6,
    "saat": 7, "sat": 7, "aath": 8, "ath": 8, "nau": 9, "das": 10, "dus": 10,
    "gyarah": 11, "barah": 12, "bara": 12, "pandrah": 15, "bees": 20,
    "pachees": 25, "tees": 30, "chalees": 40, "pachas": 50, "sau": 100,
    "adha": 0.5, "aadha": 0.5, "dedh": 1.5, "dhai": 2.5, "darjan": 12,
    # English
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9, "ten": 10, "twelve": 12, "twenty": 20, "dozen": 12,
    # Urdu script
    "ایک": 1, "دو": 2, "تین": 3, "چار": 4, "پانچ": 5, "چھ": 6, "سات": 7,
    "آٹھ": 8, "نو": 9, "دس": 10, "بارہ": 12, "بیس": 20, "پچاس": 50,
}

UNITS = {
    "carton": "carton", "cartons": "carton", "ctn": "carton", "karton": "carton",
    "کارٹن": "carton", "peti": "carton", "پیٹی": "carton", "dabba": "carton",
    "dabbay": "carton", "ڈبہ": "carton", "ڈبے": "carton", "crate": "carton",
    "packet": "pack", "packets": "pack", "pack": "pack", "packs": "pack", "پیکٹ": "pack",
    "tin": "tin", "tins": "tin", "ٹین": "tin",
    "bori": "bori", "boriyan": "bori", "بوری": "bori", "bag": "bag", "bags": "bag", "تھیلا": "bag",
    "kg": "kg", "kilo": "kg", "کلو": "kg",
    "bottle": "bottle", "bottles": "bottle", "botal": "bottle", "بوتل": "bottle",
}

FILLERS = {
    "bhai", "bhaijan", "bhai jan", "jee", "ji", "please", "plz", "salam", "assalam",
    "alaikum", "bhejo", "bhej", "bhejna", "dena", "dedo", "de", "chahiye", "chaiye",
    "bhi", "ka", "ki", "ke", "wala", "wali", "walay", "sath", "saath", "mujhe",
    "humain", "hamein", "order", "likh", "likho", "kar", "karo", "dain", "dein",
    "بھائی", "بھیج", "دیں", "دینا", "چاہیے", "بھی", "کا", "کی", "کے", "والا",
}

CREDIT_WORDS = ("udhaar", "udhar", "udhar", "ادھار", "khata", "khaate", "کھاتہ", "credit", "likh do", "likh dena", "hisaab")
CASH_WORDS = ("cash", "naqd", "nakad", "نقد", "payment kar")

SPLIT_RE = re.compile(r"[,،\n;۔]|\.(?:\s|$)|\s(?:aur|or|and|phir|plus|اور|پھر)\s", re.IGNORECASE)

MATCH_THRESHOLD = 62


def _alias_index(products: list[dict]) -> tuple[list[str], list[str]]:
    choices, owners = [], []
    for p in products:
        for alias in [p["name"], *p["aliases"]]:
            choices.append(alias.lower())
            owners.append(p["sku"])
    return choices, owners


def match_product(phrase: str, products: list[dict], limit: int = 3) -> list[tuple[str, float]]:
    """Return up to `limit` (sku, score 0-1) candidates for a spoken item phrase."""
    phrase = phrase.strip().lower()
    if not phrase:
        return []
    choices, owners = _alias_index(products)
    results = process.extract(phrase, choices, scorer=fuzz.WRatio, limit=limit * 4)
    best: dict[str, float] = {}
    for _, score, idx in results:
        sku = owners[idx]
        best[sku] = max(best.get(sku, 0), score / 100)
    return sorted(best.items(), key=lambda kv: kv[1], reverse=True)[:limit]


def detect_payment(text: str) -> str:
    lowered = text.lower()
    if any(w in lowered for w in CREDIT_WORDS):
        return "credit"
    if any(w in lowered for w in CASH_WORDS):
        return "cash"
    return "unknown"


# "likh do", "bhej do", "de do": here "do" means "give/do", not the number 2.
VERB_DO_RE = re.compile(r"\b(likh|bhej|de|kar|rakh|daal)\s*(do|dena|dein|dain)\b", re.IGNORECASE)


def _parse_segment(segment: str) -> tuple[float | None, str | None, str]:
    """Split one segment into (quantity, unit, item phrase)."""
    segment = VERB_DO_RE.sub(" ", segment)
    tokens = segment.translate(URDU_DIGITS).split()
    qty, unit, rest = None, None, []
    for tok in tokens:
        clean = tok.strip(".!?:'\"()").lower()
        if not clean:
            continue
        if qty is None and re.fullmatch(r"\d+(\.\d+)?", clean):
            qty = float(clean)
        elif qty is None and clean in NUMBER_WORDS:
            qty = float(NUMBER_WORDS[clean])
        elif unit is None and clean in UNITS:
            unit = UNITS[clean]
        elif clean in FILLERS:
            continue
        else:
            rest.append(clean)
    return qty, unit, " ".join(rest)


def offline_parse(text: str, products: list[dict]) -> dict:
    """Rule-based parse used when no AI provider is reachable."""
    lines = []
    for raw in SPLIT_RE.split(text):
        segment = (raw or "").strip()
        if not segment:
            continue
        qty, unit, phrase = _parse_segment(segment)
        if qty is None and unit is None:
            # No quantity and no unit: a greeting, a shop name or a payment
            # instruction ("udhaar likh do"), not an order line.
            continue
        candidates = match_product(phrase, products)
        if not candidates or candidates[0][1] < MATCH_THRESHOLD / 100:
            continue
        sku, score = candidates[0]
        confidence = score if qty is not None else min(score, 0.55)
        lines.append({
            "sku": sku,
            "spoken": segment,
            "quantity": qty if qty is not None else 1,
            "unit": unit,
            "confidence": round(confidence, 2),
            # Only near-ties are worth asking about.
            "alternatives": [s for s, sc in candidates[1:] if sc >= 0.75 and sc >= score - 0.05],
        })
    return {"lines": lines, "payment": detect_payment(text), "shop_hint": None}
