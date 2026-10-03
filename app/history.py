"""Simulated order history for the analytics demo.

A fresh demo database has no orders, so every chart would be empty. This seeds
45 days of plausible activity once (deterministic, seed 7): orders spread over
business hours, a voice / typed / sample mix, AI processing times, credit and
cash payments, and later khata payments. Every row is flagged `seeded = 1` so
the UI can say the history is simulated, and none of it appears in a user's
voice-note list. Today is left empty so live orders stand out.
"""

import json
import math
import random
from datetime import datetime, timedelta, timezone

from app.seed import PRODUCTS

DAYS = 45
PKT = timedelta(hours=5)

# How often each product shows up in an order (relative).
POPULARITY = {
    "PEPSI-1.5L": 9, "DALDA-TIN": 8, "SHAN-BIRYANI": 8, "TAPAL-DANEDAR": 7, "MILKPAK-1L": 7,
    "SUGAR-50KG": 6, "COKE-1.5L": 6, "SURF-EXCEL": 6, "ATTA-20KG": 6, "LIFEBUOY": 5,
    "SHAN-KARAHI": 5, "LU-PRINCE": 5, "SPRITE-1.5L": 5, "DALDA-OIL": 5, "BASMATI-5KG": 4,
}
QTY = {"carton": (1, 8), "tin": (1, 6), "pack": (2, 10), "bag": (1, 5), "bori": (1, 4), "kg": (5, 25)}


def _qty(rng: random.Random, unit: str) -> float:
    lo, hi = QTY.get(unit, (1, 5))
    q = rng.randint(lo, hi)
    if unit == "kg":
        return float(5 * max(1, round(q / 5)))
    if unit == "carton" and rng.random() < 0.08:
        return q + 0.5
    return float(q)


def seed_history(conn) -> None:
    if conn.execute("SELECT value FROM meta WHERE key = 'history_seeded'").fetchone():
        return
    rng = random.Random(7)
    shops = [r["id"] for r in conn.execute("SELECT id FROM shops ORDER BY id")]
    shop_weights = [6, 5, 3, 7, 4, 3][: len(shops)]
    products = [p for p in PRODUCTS]
    weights = [POPULARITY.get(p[0], 2) for p in products]

    today_pkt = (datetime.now(timezone.utc) + PKT).date()
    orders, ledger = [], []
    for days_ago in range(DAYS, 0, -1):
        day = today_pkt - timedelta(days=days_ago)
        progress = 1 - days_ago / DAYS                        # adoption grows over the period
        base = 5 + 7 * progress
        if day.weekday() == 4:                                 # Friday: shorter trading day
            base *= 0.7
        count = max(1, round(rng.gauss(base, 1.6)))
        for _ in range(count):
            hour_pkt = rng.choices(range(9, 21), weights=[3, 6, 8, 7, 5, 4, 5, 7, 8, 6, 4, 2])[0]
            created = datetime(day.year, day.month, day.day, hour_pkt, rng.randint(0, 59),
                               rng.randint(0, 59), tzinfo=timezone.utc) - PKT
            shop_id = rng.choices(shops, weights=shop_weights)[0]

            picked = {}
            for _ in range(rng.choices([1, 2, 3, 4, 5], weights=[2, 4, 4, 3, 1])[0]):
                sku, name, unit, price, _aliases = rng.choices(products, weights=weights)[0]
                if sku not in picked:
                    q = _qty(rng, unit)
                    picked[sku] = {"sku": sku, "name": name, "unit": unit,
                                   "quantity": int(q) if q.is_integer() else q,
                                   "price": price, "line_total": round(price * q)}
            lines = list(picked.values())
            total = sum(l["line_total"] for l in lines)

            voice_share = 0.5 + 0.2 * progress
            source = rng.choices(["voice", "text", "sample"], weights=[voice_share, 0.88 - voice_share, 0.12])[0]
            mode = "ai"
            if source == "voice":
                ms = rng.lognormvariate(math.log(2600), 0.32)
            elif source == "text":
                ms = rng.lognormvariate(math.log(1300), 0.35)
            else:
                ms, mode = rng.uniform(80, 220), "cached"
            if source != "sample" and rng.random() < 0.04:     # provider busy: offline fallback
                ms, mode = rng.uniform(150, 400) + (900 if source == "voice" else 0), "offline"
            review = sum(1 for _ in lines if rng.random() < (0.13 if source == "voice" else 0.07))
            payment = rng.choices(["credit", "cash", "unknown"], weights=[60, 36, 4])[0]

            orders.append((shop_id, created.isoformat(timespec="seconds"), "(simulated history)",
                           payment, total, source, json.dumps(lines), round(min(ms, 9000)), review, mode))
            if payment == "credit":
                ledger.append((shop_id, created, "credit_order", total, "Order (simulated history)"))
                if rng.random() < 0.85:
                    paid_at = created + timedelta(days=rng.randint(3, 10), hours=rng.randint(0, 6))
                    if paid_at.date() < today_pkt:
                        amount = total if rng.random() < 0.7 else round(total * 0.5)
                        ledger.append((shop_id, paid_at, "payment", -amount, "Payment (simulated history)"))

    orders.sort(key=lambda o: o[1])
    conn.executemany(
        """INSERT INTO orders (shop_id, created_at, transcript, payment, total, source, lines_json,
                               processing_ms, review_lines, ai_mode, seeded)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        orders,
    )
    ledger.sort(key=lambda e: e[1])
    conn.executemany(
        "INSERT INTO ledger (shop_id, created_at, kind, amount, note, seeded) VALUES (?, ?, ?, ?, ?, 1)",
        [(s, t.isoformat(timespec="seconds"), k, a, n) for s, t, k, a, n in ledger],
    )
    conn.execute("INSERT INTO meta (key, value) VALUES ('history_seeded', ?)", (str(len(orders)),))
