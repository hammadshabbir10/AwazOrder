"""Order receipts: one data shape, rendered as PDF (fpdf2) or CSV.

The receipt is built from an order snapshot, the same signed one the
confirmation screen holds, so it can be produced on any server instance.
"""

import csv
import io
from datetime import datetime, timedelta

from fpdf import FPDF

PKT = timedelta(hours=5)
PAYMENT_LABEL = {"credit": "Khata (credit)", "cash": "Cash on delivery", "unknown": "Pending: ask the shop"}

NAVY = (29, 53, 87)
INK = (15, 27, 45)
MUTED = (102, 115, 138)
LINE = (227, 232, 240)
ZEBRA = (246, 247, 251)
ACCENT = (224, 122, 47)


def receipt_number(order_id: int) -> str:
    return f"AO-{order_id:06d}"


def pkt_time(iso: str) -> str:
    dt = datetime.fromisoformat(iso) + PKT
    hour = dt.hour % 12 or 12
    return f"{dt.day} {dt.strftime('%b %Y')}, {hour}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'} PKT"


def _t(value) -> str:
    """Text safe for the PDF core fonts (Latin-1)."""
    s = str(value)
    for a, b in (("—", "-"), ("–", "-"), ("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'), ("…", "..."), ("‏", "")):
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


def _qty(q) -> str:
    q = float(q)
    return str(int(q)) if q.is_integer() else f"{q:g}"


def _rs(n) -> str:
    return f"Rs {round(n):,}"


def build_pdf(r: dict) -> bytes:
    """r: id, created_at, shop{name, area, phone}, lines, total, payment, balance, distributor."""
    pdf = FPDF(format=(148, 210), unit="mm")  # A5
    pdf.set_auto_page_break(auto=True, margin=16)
    pdf.set_title(f"Receipt {receipt_number(r['id'])}")
    pdf.set_author(_t(r["distributor"]))
    pdf.add_page()
    W = pdf.w - 20  # 10 mm margins

    # Header band
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, pdf.w, 30, style="F")
    pdf.set_xy(10, 8)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(W * 0.6, 7, _t(r["distributor"]))
    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(W * 0.4, 7, "ORDER RECEIPT", align="R")
    pdf.set_xy(10, 16)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(205, 216, 234)
    pdf.cell(W * 0.6, 5, "Order desk powered by Awaz Order")
    pdf.cell(W * 0.4, 5, receipt_number(r["id"]), align="R")

    # Receipt meta + bill to
    pdf.set_xy(10, 37)
    pdf.set_text_color(*MUTED)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.cell(W / 2, 4, "BILL TO")
    pdf.cell(W / 2, 4, "DETAILS", align="R")
    pdf.ln(5)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "B", 10.5)
    pdf.cell(W / 2, 5.5, _t(r["shop"]["name"]))
    pdf.set_font("Helvetica", "", 8.5)
    pdf.cell(W / 2, 5.5, _t(f"Date: {pkt_time(r['created_at'])}"), align="R")
    pdf.ln(5.5)
    pdf.set_text_color(*MUTED)
    pdf.cell(W / 2, 4.5, _t(r["shop"].get("area", "")))
    pdf.cell(W / 2, 4.5, _t(f"Payment: {PAYMENT_LABEL.get(r['payment'], r['payment'])}"), align="R")
    pdf.ln(4.5)
    pdf.cell(W / 2, 4.5, _t(r["shop"].get("phone", "")))
    pdf.ln(9)

    # Items table
    cols = [("#", 7, "C"), ("Item", W - 7 - 13 - 15 - 22 - 25, "L"), ("Qty", 13, "R"),
            ("Unit", 15, "L"), ("Rate", 22, "R"), ("Amount", 25, "R")]
    pdf.set_fill_color(*NAVY)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 8)
    for name, w, align in cols:
        pdf.cell(w, 7, name, fill=True, align=align)
    pdf.ln(7)
    pdf.set_text_color(*INK)
    pdf.set_font("Helvetica", "", 8.5)
    for i, l in enumerate(r["lines"], 1):
        fill = i % 2 == 0
        pdf.set_fill_color(*ZEBRA)
        values = [str(i), _t(l["name"]), _qty(l["quantity"]), _t(l["unit"]), f"{l['price']:,}", f"{l['line_total']:,}"]
        for (name, w, align), v in zip(cols, values):
            pdf.cell(w, 7, v, fill=fill, align=align)
        pdf.ln(7)
    pdf.set_draw_color(*LINE)
    pdf.line(10, pdf.get_y(), 10 + W, pdf.get_y())
    pdf.ln(3)

    # Totals
    label_w, value_w = W - 40, 40
    def total_row(label, value, bold=False, color=INK, size=9, height=6):
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.set_text_color(*MUTED if not bold else color)
        pdf.cell(label_w, height, label, align="R")
        pdf.set_text_color(*color)
        pdf.cell(value_w, height, value, align="R")
        pdf.ln(height)

    items = sum(float(l["quantity"]) for l in r["lines"])
    total_row(f"{len(r['lines'])} line(s), {_qty(items)} unit(s)", "")
    pdf.ln(1)
    pdf.set_fill_color(*ZEBRA)
    pdf.rect(10 + label_w - 34, pdf.get_y(), 34 + value_w, 10, style="F")  # box behind TOTAL
    total_row("TOTAL", _rs(r["total"]), bold=True, color=NAVY, size=12, height=10)
    pdf.ln(1)
    if r["payment"] == "credit":
        total_row("Added to khata", _rs(r["total"]))
        total_row("Khata balance after this order", _rs(r["balance"]), bold=True, color=ACCENT, size=9.5)
    elif r["payment"] == "cash":
        total_row("To collect on delivery", _rs(r["total"]), bold=True, color=ACCENT, size=9.5)
    else:
        total_row("Payment method", "Pending", bold=True, color=ACCENT, size=9.5)

    # Footer, pinned to the bottom of the page (no automatic page break here)
    pdf.set_auto_page_break(False)
    if pdf.get_y() > pdf.h - 30:      # totals reach the footer area: footer on its own page
        pdf.add_page()
    pdf.set_y(-24)
    pdf.set_draw_color(*LINE)
    pdf.line(10, pdf.get_y(), 10 + W, pdf.get_y())
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*INK)
    pdf.cell(W, 5, "Thank you for your order.", align="C")
    pdf.ln(5)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.cell(W, 4, _t("Generated by Awaz Order, the AI order desk for distributors. Demo data: prices are illustrative."), align="C")
    return bytes(pdf.output())


def build_csv(r: dict) -> str:
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Receipt", receipt_number(r["id"])])
    w.writerow(["Date", pkt_time(r["created_at"])])
    w.writerow(["Shop", r["shop"]["name"]])
    w.writerow(["Payment", PAYMENT_LABEL.get(r["payment"], r["payment"])])
    w.writerow([])
    w.writerow(["#", "Item", "SKU", "Quantity", "Unit", "Rate (Rs)", "Amount (Rs)"])
    for i, l in enumerate(r["lines"], 1):
        w.writerow([i, l["name"], l["sku"], _qty(l["quantity"]), l["unit"], l["price"], l["line_total"]])
    w.writerow([])
    w.writerow(["", "", "", "", "", "Total (Rs)", r["total"]])
    if r["payment"] == "credit":
        w.writerow(["", "", "", "", "", "Khata balance (Rs)", r["balance"]])
    return out.getvalue()
