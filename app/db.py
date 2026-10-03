"""SQLite storage. The demo database is created and seeded on startup."""

import hashlib
import json
import os
import secrets
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone

from app.history import seed_history
from app.seed import CREDIT_LIMITS, DEFAULT_CREDIT_LIMIT, DEMO_USER, PRODUCTS, SHOPS

# Serverless hosts (Vercel) only allow writes under /tmp.
_DEFAULT_DB = os.path.join(tempfile.gettempdir(), "awaz.db") if os.environ.get("VERCEL") else os.path.join(os.path.dirname(__file__), "..", "awaz.db")
DB_PATH = os.environ.get("DB_PATH", _DEFAULT_DB)

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS products (
    sku TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    unit TEXT NOT NULL,
    price INTEGER NOT NULL,
    aliases TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shops (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    area TEXT NOT NULL,
    phone TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    created_at TEXT NOT NULL,
    transcript TEXT NOT NULL,
    payment TEXT NOT NULL,
    total INTEGER NOT NULL,
    source TEXT NOT NULL,
    lines_json TEXT NOT NULL,
    reply TEXT NOT NULL DEFAULT '',
    spoken TEXT NOT NULL DEFAULT '',
    note_id INTEGER
);
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,          -- voice | text
    transcript TEXT NOT NULL,
    audio_path TEXT,
    duration REAL,
    draft_json TEXT NOT NULL,
    order_id INTEGER
);
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ledger (
    id INTEGER PRIMARY KEY,
    shop_id INTEGER NOT NULL REFERENCES shops(id),
    created_at TEXT NOT NULL,
    kind TEXT NOT NULL,          -- opening | credit_order | payment
    amount INTEGER NOT NULL,     -- positive = shop owes more, negative = paid
    note TEXT NOT NULL,
    order_id INTEGER
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    salt, _ = stored.split("$", 1)
    return secrets.compare_digest(hash_password(password, salt), stored)


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created."""
    for table, columns in (
        ("orders", (
            ("reply", "TEXT NOT NULL DEFAULT ''"),
            ("spoken", "TEXT NOT NULL DEFAULT ''"),
            ("note_id", "INTEGER"),
            ("processing_ms", "INTEGER"),      # voice/text -> draft time, for analytics
            ("review_lines", "INTEGER"),       # lines the AI flagged as uncertain
            ("ai_mode", "TEXT"),               # ai | offline | cached
            ("seeded", "INTEGER NOT NULL DEFAULT 0"),
        )),
        ("ledger", (("seeded", "INTEGER NOT NULL DEFAULT 0"),)),
    ):
        have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        for column, ddl in columns:
            if column not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
            conn.execute(
                "INSERT INTO users (email, name, password_hash) VALUES (?, ?, ?)",
                (DEMO_USER["email"], DEMO_USER["name"], hash_password(DEMO_USER["password"])),
            )
        if conn.execute("SELECT COUNT(*) FROM products").fetchone()[0] == 0:
            conn.executemany(
                "INSERT INTO products (sku, name, unit, price, aliases) VALUES (?, ?, ?, ?, ?)",
                [(s, n, u, p, json.dumps(a, ensure_ascii=False)) for s, n, u, p, a in PRODUCTS],
            )
        if conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0] == 0:
            for name, area, phone, opening in SHOPS:
                cur = conn.execute(
                    "INSERT INTO shops (name, area, phone) VALUES (?, ?, ?)", (name, area, phone)
                )
                if opening:
                    conn.execute(
                        "INSERT INTO ledger (shop_id, created_at, kind, amount, note) VALUES (?, ?, 'opening', ?, 'Opening balance')",
                        (cur.lastrowid, now(), opening),
                    )
        if os.environ.get("SEED_HISTORY", "1") == "1":
            seed_history(conn)


def get_products() -> list[dict]:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
    return [{**dict(r), "aliases": json.loads(r["aliases"])} for r in rows]


def get_shops() -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            """SELECT s.*, COALESCE(SUM(l.amount), 0) AS balance
               FROM shops s LEFT JOIN ledger l ON l.shop_id = s.id
               GROUP BY s.id ORDER BY s.name"""
        ).fetchall()
    return [{**dict(r), "credit_limit": CREDIT_LIMITS.get(r["name"], DEFAULT_CREDIT_LIMIT)} for r in rows]
