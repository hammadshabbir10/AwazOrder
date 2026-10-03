"""Multi-agent order pipeline.

Each agent has one job, one engine (a model or a deterministic tool) and hands
a structured result to the next. The orchestrator records a trace of every
step (engine, time, decision) that the UI shows next to the draft.

    Listener   voice note -> transcript                    Whisper large-v3
    Router     transcript -> intent: order / payment /     fast LLM (gpt-oss-20b)
               balance question / other
    Extraction transcript -> items, quantities, payment    Qwen 3.8 -> gpt-oss-120b
    Catalogue  items -> validated, priced catalogue lines   RapidFuzz + database
    Verifier   transcript + lines -> issues, corrections    fast LLM, a second opinion
    Credit     shop + amount -> khata vs credit limit      rules over the ledger

The Reply and Voice agents run when the order is confirmed (pipeline.py and
ai.speak). Every LLM agent has a deterministic fallback, so the pipeline still
completes when the AI service is busy.
"""

import json
import re
import time
from concurrent.futures import ThreadPoolExecutor

from app import ai
from app.db import get_products, get_shops
from app.parser import NUMBER_WORDS, URDU_DIGITS, offline_parse
from app.pipeline import (NoSpeech, WHISPER_SILENCE, _normalise, build_line, find_shop,
                          vocabulary_hint)

AGENTS = {
    "listener": ("Listener", "Turns the voice note into text"),
    "router": ("Router", "Works out what the shopkeeper wants"),
    "extractor": ("Extraction", "Pulls out items, quantities, payment and shop"),
    "catalogue": ("Catalogue", "Matches products and prices them from the database"),
    "verifier": ("Verifier", "Double-checks the order against what was said"),
    "credit": ("Credit", "Checks the shop's khata against its credit limit"),
}
INTENTS = ("order", "payment", "balance", "other")


class Trace:
    """Ordered record of agent steps, returned with the draft."""

    def __init__(self):
        self.steps: list[dict] = []

    def run(self, key: str, fn, engine: str = ""):
        name, job = AGENTS[key]
        step = {"key": key, "name": name, "job": job, "engine": engine, "status": "ok",
                "summary": "", "notes": []}
        started = time.perf_counter()
        try:
            result = fn(step)
        finally:
            step["ms"] = round((time.perf_counter() - started) * 1000)
            self.steps.append(step)
        return result

    def skip(self, key: str, reason: str):
        name, job = AGENTS[key]
        self.steps.append({"key": key, "name": name, "job": job, "engine": "", "status": "skipped",
                           "summary": reason, "notes": [], "ms": 0})


def _model(name: str | None) -> str:
    return (name or "").split(":", 1)[-1]


# ---------------------------------------------------------------- Router agent

ROUTER_PROMPT = """You route WhatsApp messages that Pakistani shopkeepers send to their goods distributor.
Messages are informal Urdu, Roman Urdu, Punjabi or English, often transcribed from a voice note.

Decide the intent:
- "order": they want goods sent (products and quantities).
- "payment": they say they have paid or sent money ("bees hazar bhej diye", "payment kar di", "jama karwa diye").
- "balance": they ask how much they owe ("mera kitna baqaya hai", "hisaab bata dein").
- "other": anything else (greetings only, complaints, delivery questions).
If a message both orders goods and mentions money, the intent is "order".

For "payment", give the amount in rupees as a number (bees hazar = 20000, dedh lakh = 150000, 1 lakh = 100000).
Return ONLY JSON: {"intent":"order|payment|balance|other","confidence":0.0,"amount":null,"shop_hint":null,"reason":"short English"}"""

PAYMENT_WORDS = ("bhej diye", "bhej di", "bhej dia", "bheje", "jama", "payment", "paise", "paisay", "raqam",
                 "transfer", "easypaisa", "jazzcash", "ادا", "بھیج دی", "جمع", "ادائیگی")
BALANCE_WORDS = ("kitna", "kitne", "baqaya", "baqi", "balance", "hisaab", "hisab", "بقایا", "کتنا", "حساب")
MULTIPLIERS = {"hazar": 1_000, "hazaar": 1_000, "thousand": 1_000, "k": 1_000, "ہزار": 1_000,
               "lakh": 100_000, "lac": 100_000, "لاکھ": 100_000, "crore": 10_000_000, "کروڑ": 10_000_000}


def parse_amount(text: str) -> int | None:
    """Rupee amount from words or digits: '20,000', 'bees hazar', 'dedh lakh'."""
    tokens = re.findall(r"[\w؀-ۿ.]+", text.translate(URDU_DIGITS).replace(",", "").lower())
    best = None
    for i, tok in enumerate(tokens):
        value = float(tok) if re.fullmatch(r"\d+(\.\d+)?", tok) else NUMBER_WORDS.get(tok)
        if value is None:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
        amount = value * MULTIPLIERS.get(nxt, 1)
        if amount >= 100 and (best is None or amount > best):
            best = amount
    return round(best) if best else None


def _route_rules(text: str, products: list[dict]) -> dict:
    lowered = text.lower()
    if offline_parse(text, products)["lines"]:
        return {"intent": "order", "confidence": 0.7, "reason": "Found catalogue items"}
    if any(w in lowered for w in PAYMENT_WORDS) and parse_amount(text):
        return {"intent": "payment", "confidence": 0.7, "amount": parse_amount(text), "reason": "Payment words and an amount"}
    if any(w in lowered for w in BALANCE_WORDS):
        return {"intent": "balance", "confidence": 0.7, "reason": "Asked about their balance"}
    return {"intent": "other", "confidence": 0.5, "reason": "No order, payment or balance question found"}


def router_agent(transcript: str, products: list[dict], use_ai: bool):
    def step(s):
        result = None
        if use_ai:
            try:
                result, name = ai.chat_json(ROUTER_PROMPT, transcript, role="agent", require="intent")
                s["engine"] = _model(name)
            except ai.AllProvidersFailed:
                s["status"] = "fallback"
        if not result or result.get("intent") not in INTENTS:
            result = _route_rules(transcript, products)
            s["engine"] = "keyword rules"
            if use_ai:
                s["status"] = "fallback"
        if result.get("intent") == "payment" and not result.get("amount"):
            result["amount"] = parse_amount(transcript)
        labels = {"order": "New order", "payment": "Payment report", "balance": "Balance question", "other": "Not an order"}
        s["summary"] = f"{labels[result['intent']]} ({round(float(result.get('confidence') or 0.7) * 100)}% sure)"
        if result.get("reason"):
            s["notes"].append(result["reason"])
        return result
    return step


# ---------------------------------------------------------------- Extraction + Catalogue agents

def extraction_agent(transcript: str, products: list[dict], use_ai: bool, ctx: dict):
    def step(s):
        raw = None
        if use_ai:
            try:
                raw, name = ai.extract_order(transcript, products)
                s["engine"] = _model(name)
                ctx["mode"], ctx["provider"] = "ai", name
            except ai.AllProvidersFailed as exc:
                ctx["ai_error"] = str(exc)
                s["status"] = "fallback"
        if raw is None:
            raw = offline_parse(transcript, products)
            s["engine"] = "offline parser"
        pay = {"credit": "khata", "cash": "cash"}.get(raw.get("payment"), "not said")
        s["summary"] = f"{len(raw.get('lines', []))} items · payment {pay}"
        if raw.get("unmatched"):
            s["notes"].append(f"Not in catalogue: {', '.join(raw['unmatched'])}")
        return raw
    return step


def catalogue_agent(raw: dict, products: list[dict], transcript: str):
    def step(s):
        known = {p["sku"] for p in products}
        rematched = sum(1 for item in raw.get("lines", []) if item.get("sku") not in known)
        draft = _normalise(raw, products, transcript)
        flagged = sum(1 for l in draft["lines"] if l["needs_review"])
        s["engine"] = "RapidFuzz + price list"
        s["summary"] = f"{len(draft['lines'])} lines priced · Rs {draft['total']:,}"
        if rematched:
            s["notes"].append(f"Re-matched {rematched} product name(s) the model got wrong")
        if flagged:
            s["notes"].append(f"{flagged} line(s) uncertain, highlighted for review")
        return draft
    return step


# ---------------------------------------------------------------- Verifier agent

VERIFIER_PROMPT = """You are a strict auditor checking an AI's reading of a shopkeeper's order before a person confirms it.
Compare what the shopkeeper said with the extracted lines. Report ONLY real problems:
- "missing": a product they clearly ordered is not in the lines
- "quantity": a line's quantity is wrong (if they corrected themselves, the final number counts)
- "not_ordered": a line they never asked for
Use only skus from this catalogue (sku | product | unit | aliases):
{catalogue}

If everything matches, return approved true and no issues. Do not repeat correct lines.
Return ONLY JSON: {{"approved":true,"issues":[{{"type":"missing|quantity|not_ordered","sku":"...","quantity":null,"reason":"short English"}}]}}"""


def verifier_agent(draft: dict, products: list[dict]):
    def step(s):
        by_sku = {p["sku"]: p for p in products}
        payload = json.dumps({
            "said": draft["transcript"],
            "lines": [{"sku": l["sku"], "product": l["name"], "quantity": l["quantity"]} for l in draft["lines"]],
        }, ensure_ascii=False)
        try:
            verdict, name = ai.chat_json(VERIFIER_PROMPT.format(catalogue=ai.catalogue_text(products)), payload,
                                         role="agent", require="approved")
        except ai.AllProvidersFailed:
            s["status"], s["engine"] = "skipped", ""
            s["summary"] = "AI busy, so the human review step covers this order"
            return
        s["engine"] = _model(name)
        applied = 0
        for issue in verdict.get("issues") or []:
            kind, sku, reason = issue.get("type"), issue.get("sku"), (issue.get("reason") or "").strip()
            line = next((l for l in draft["lines"] if l["sku"] == sku), None)
            qty = issue.get("quantity")
            try:
                qty = float(qty) if qty is not None else None
            except (TypeError, ValueError):
                qty = None
            if kind == "quantity" and line and qty and qty > 0 and qty != line["quantity"]:
                idx = draft["lines"].index(line)
                draft["lines"][idx] = build_line(by_sku, sku, qty, line["spoken"], min(line["confidence"], 0.7),
                                                 review_reason=f"Verifier changed {line['quantity']} to {qty:g}: {reason}")
                applied += 1
            elif kind == "missing" and sku in by_sku and not line:
                draft["lines"].append(build_line(by_sku, sku, qty if qty and qty > 0 else 1, "", 0.6,
                                                 review_reason=f"Verifier added a missed item: {reason}"))
                applied += 1
            elif kind == "not_ordered" and line:
                line["needs_review"] = True
                line["review_reason"] = f"Verifier thinks this may not have been ordered: {reason}"
                applied += 1
            else:
                continue
            s["notes"].append(reason or kind)
        draft["total"] = sum(l["line_total"] for l in draft["lines"])
        if applied:
            s["status"] = "warn"
            s["summary"] = f"Found {applied} issue{'s' if applied > 1 else ''}, highlighted for review"
        else:
            s["summary"] = "Order matches what was said"
    return step


# ---------------------------------------------------------------- Credit agent

def credit_check(shop: dict, amount: int, kind: str = "order") -> dict:
    limit, balance = shop["credit_limit"], shop["balance"]
    after = balance + amount if kind == "order" else balance - amount
    ratio = after / limit if limit else 0
    status = "over" if ratio > 1 else "warn" if ratio > 0.8 else "ok"
    return {"shop_id": shop["id"], "shop": shop["name"], "balance": balance, "limit": limit,
            "after": after, "status": status, "used_pct": round(ratio * 100)}


def credit_agent(draft: dict, shops: list[dict], kind: str = "order", amount: int | None = None):
    def step(s):
        s["engine"] = "khata ledger rules"
        shop = next((x for x in shops if x["id"] == draft.get("shop_id")), None)
        if not shop:
            s["status"] = "skipped"
            s["summary"] = "Shop not named, so it's checked when you choose the shop"
            return None
        value = draft["total"] if kind == "order" else (amount or 0)
        check = credit_check(shop, value, kind)
        if kind == "order" and draft.get("payment") == "cash":
            s["summary"] = f"Cash order · {shop['name']} owes Rs {shop['balance']:,}"
            check["status"] = "ok"
            return check
        if kind == "balance":
            s["summary"] = f"{shop['name']} owes Rs {shop['balance']:,} of Rs {shop['credit_limit']:,} limit"
            return check
        verb = "after this order" if kind == "order" else "after this payment"
        s["summary"] = f"Rs {check['after']:,} {verb} · {check['used_pct']}% of limit"
        if kind == "payment":
            if check["status"] != "ok":
                s["status"] = "warn"
                s["notes"].append(f"Still above 80% of the credit limit after this payment")
            return check
        if check["status"] == "over":
            s["status"] = "warn"
            s["notes"].append(f"Over the Rs {check['limit']:,} credit limit: ask for payment first")
        elif check["status"] == "warn":
            s["status"] = "warn"
            s["notes"].append("Close to the credit limit")
        return check
    return step


# ---------------------------------------------------------------- orchestrator

def run(transcript: str, use_ai: bool = True, forced_intent: str | None = None, trace: Trace | None = None) -> dict:
    trace = trace or Trace()
    products, shops = get_products(), get_shops()
    ctx = {"mode": "offline", "provider": None, "ai_error": None}
    started = time.perf_counter()

    raw = None
    if forced_intent in INTENTS:
        route = {"intent": forced_intent, "confidence": 1.0, "reason": "Chosen by the user"}
        trace.skip("router", "Intent set by you: " + forced_intent)
    elif use_ai:
        # Router and Extraction run in parallel: most messages are orders, so the
        # extraction is usually needed anyway and the order arrives ~1-2 s sooner.
        # If the Router says it's not an order, the extraction is discarded.
        side = Trace()
        with ThreadPoolExecutor(max_workers=2) as pool:
            routing = pool.submit(side.run, "router", router_agent(transcript, products, use_ai))
            extracting = pool.submit(side.run, "extractor", extraction_agent(transcript, products, use_ai, ctx))
            route, raw = routing.result(), extracting.result()
        steps = {s["key"]: s for s in side.steps}
        trace.steps.append(steps["router"])
        if route["intent"] == "order":
            steps["extractor"]["notes"].append("Ran in parallel with the Router")
            trace.steps.append(steps["extractor"])
        else:
            raw = None
            ctx.update({"mode": "offline", "provider": None, "ai_error": None})
    else:
        route = trace.run("router", router_agent(transcript, products, use_ai))
    intent = route["intent"]

    if intent == "order":
        if raw is None:
            raw = trace.run("extractor", extraction_agent(transcript, products, use_ai, ctx))
        draft = trace.run("catalogue", catalogue_agent(raw, products, transcript))
        if ctx["mode"] == "ai" and draft["lines"]:
            trace.run("verifier", verifier_agent(draft, products))
        else:
            trace.skip("verifier", "Skipped: no AI extraction to check" if draft["lines"] else "No items to check")
        draft["credit"] = trace.run("credit", credit_agent(draft, shops))
    else:
        shop_id = find_shop(route.get("shop_hint"), shops, transcript)
        draft = {"transcript": transcript, "lines": [], "unmatched": [], "payment": "unknown",
                 "shop_id": shop_id, "total": 0}
        if intent == "payment":
            draft["amount"] = route.get("amount")
            draft["credit"] = trace.run("credit", credit_agent(draft, shops, "payment", route.get("amount")))
        elif intent == "balance":
            draft["credit"] = trace.run("credit", credit_agent(draft, shops, "balance"))
        router = next((x for x in trace.steps if x["key"] == "router"), None)
        if router and router["status"] == "ok" and router["engine"] != "keyword rules":
            ctx["mode"], ctx["provider"] = "ai", router["engine"]

    agents_ms = round((time.perf_counter() - started) * 1000)
    draft.update({
        "intent": intent,
        "route": route,
        "mode": ctx["mode"],
        "provider": ctx["provider"],
        "ai_error": ctx["ai_error"],
        "agents": trace.steps,
        "timing": {"extract_ms": agents_ms, "total_ms": agents_ms},
    })
    return draft


def run_audio(audio: bytes, filename: str, content_type: str) -> dict:
    trace = Trace()
    products = get_products()

    def listen(s):
        transcript, name = ai.transcribe(audio, filename, content_type, vocabulary_hint(products))
        s["engine"] = _model(name)
        words = len(transcript.split())
        s["summary"] = f"Heard {words} word{'s' if words != 1 else ''}"
        return transcript, name

    transcript, asr_provider = trace.run("listener", listen)
    asr_ms = trace.steps[-1]["ms"]
    cleaned = transcript.strip(" .۔!?،,").lower()
    if len(cleaned) < 4 or cleaned in WHISPER_SILENCE:
        raise NoSpeech()
    draft = run(transcript, trace=trace)
    draft["asr_provider"] = asr_provider
    extract_ms = draft["timing"]["extract_ms"]
    draft["timing"] = {"asr_ms": asr_ms, "extract_ms": extract_ms, "total_ms": asr_ms + extract_ms}
    return draft
