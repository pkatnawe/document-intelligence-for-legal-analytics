"""Evaluation harness — the ground-truth environment for benchmarking extraction.

Three pieces, kept small and reusable:
  * `load_gold()`   — the verified gold set + the rendered page image / text for each invoice.
  * `score()`       — a normalizing metric: per-field accuracy + line-item F1 -> one 0..1 score.
  * `dspy_metric()` — the same score wrapped as a DSPy metric, so GEPA/optimizers can train on it.

The metric normalizes before comparing (case, whitespace, currency symbols, date formats,
money rounding) so a *correct* read isn't punished for formatting — we measure whether the
model got the value right, not whether it matched a string byte-for-byte.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from app.validation.schema import Invoice

GOLD_DIR = Path(__file__).parent / "gold"
# The case PDF lives outside the repo (it's the firm's data); override with $CASE_PDF.
DEFAULT_PDF = Path("/Users/pkatnawe/Work/Compass/case_interview_dataset.pdf")

# Header fields we score, and how much each is worth. Money + identity fields matter most.
FIELD_WEIGHTS = {
    "invoice_number": 2.0, "total": 2.0, "vendor": 1.5, "tax": 1.5, "subtotal": 1.0,
    "currency": 1.0, "invoice_date": 1.0, "bill_to": 1.0, "payment_method": 1.0,
    "due_date": 0.5, "purchase_order": 0.5,
}
LINE_ITEMS_WEIGHT = 3.0  # the hardest part of the task -> weighted heaviest


@dataclass
class GoldDoc:
    name: str
    page: int
    doc_type: str
    gold: Invoice
    notes: str = ""
    text: Optional[str] = None          # the PDF's text layer (empty for these scans)
    image_uri: Optional[str] = None     # data: URI of the rendered page (filled lazily)
    _pdf: bytes = field(default=None, repr=False)


def load_gold(pdf_path: Optional[Path] = None) -> list[GoldDoc]:
    """Load every gold file and attach the rendered page image + any text layer."""
    from app.documents.loader import load_pdf, png_to_data_uri
    from app.documents.splitter import split_pdf

    pdf_path = Path(pdf_path or __import__("os").environ.get("CASE_PDF", DEFAULT_PDF))
    pages = split_pdf(pdf_path.read_bytes())
    by_page = {sp.index: sp.pdf for sp in pages}

    docs: list[GoldDoc] = []
    for gf in sorted(GOLD_DIR.glob("*.json")):
        raw = json.loads(gf.read_text())
        page = int(raw["source"].split("page=")[-1])
        doc = load_pdf(by_page[page])
        docs.append(GoldDoc(
            name=gf.stem, page=page, doc_type=raw["doc_type"], notes=raw.get("notes", ""),
            gold=Invoice.model_validate(raw["invoice"]),
            text=doc.text if doc.has_text else None,
            image_uri=png_to_data_uri(doc.page_images_png[0]) if doc.page_images_png else None,
            _pdf=by_page[page],
        ))
    return docs


# ----------------------------- normalization -----------------------------

def _norm_str(v) -> str:
    if v is None:
        return ""
    s = re.sub(r"[^a-z0-9@. ]", " ", str(v).lower())  # keep @ and . for emails
    return re.sub(r"\s+", " ", s).strip()


def _norm_currency(v) -> str:
    if v is None:
        return ""
    s = str(v).upper().strip()
    if "CA" in s or s == "C$":
        return "CAD"
    if "US" in s:
        return "USD"
    if s in {"$"}:
        return "USD"  # ambiguous; gold encodes the real one, this only normalizes symbols
    return re.sub(r"[^A-Z]", "", s)[:3] or s


_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def _norm_date(v) -> str:
    """Best-effort -> YYYY-MM-DD. Handles 'June 17, 2025', 'Jul 01 2025', '6/17/25', ISO."""
    if v is None:
        return ""
    s = str(v).strip().lower()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.search(r"([a-z]{3,})\w*\.?\s+(\d{1,2}),?\s+(\d{4})", s)  # June 17, 2025 / Jul 01 2025
    if m and m.group(1)[:3] in _MONTHS:
        return f"{int(m.group(3)):04d}-{_MONTHS[m.group(1)[:3]]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2,4})", s)  # 6/17/25
    if m:
        y = int(m.group(3)); y += 2000 if y < 100 else 0
        return f"{y:04d}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return s


def _money_eq(a, b, tol=0.01) -> bool:
    if a is None and b is None:
        return True
    if a is None or b is None:
        return False
    return abs(float(a) - float(b)) <= tol


def _field_correct(name: str, pred, gold) -> bool:
    if name in {"total", "tax", "subtotal"}:
        return _money_eq(pred, gold)
    if name in {"invoice_date", "due_date"}:
        return _norm_date(pred) == _norm_date(gold)
    if name == "currency":
        return _norm_currency(pred) == _norm_currency(gold)
    gp, gg = _norm_str(pred), _norm_str(gold)
    if name in {"vendor", "bill_to", "payment_method"} and gp and gg:
        return gp == gg or gp in gg or gg in gp  # lenient: containment for free-text identity
    return gp == gg


# ----------------------------- line-item F1 -----------------------------

def _line_item_f1(pred_items, gold_items) -> tuple[float, float, float]:
    """Greedy match by amount (within tol) AND overlapping description tokens."""
    gold = list(gold_items)
    matched = 0
    for p in pred_items:
        for i, g in enumerate(gold):
            same_amt = _money_eq(p.amount, g.amount)
            pt, gt = set(_norm_str(p.description).split()), set(_norm_str(g.description).split())
            same_desc = bool(pt & gt)
            if same_amt and same_desc:
                matched += 1
                gold.pop(i)
                break
    p_n, g_n = len(list(pred_items)), len(list(gold_items))
    precision = matched / p_n if p_n else (1.0 if g_n == 0 else 0.0)
    recall = matched / g_n if g_n else 1.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


# ----------------------------- scoring -----------------------------

def score(pred: Invoice, gold: Invoice) -> dict:
    """Per-field correctness + line-item F1 -> a single weighted 0..1 score."""
    fields = {name: _field_correct(name, getattr(pred, name), getattr(gold, name))
              for name in FIELD_WEIGHTS}
    p, r, f1 = _line_item_f1(pred.line_items, gold.line_items)

    earned = sum(FIELD_WEIGHTS[n] for n, ok in fields.items() if ok) + LINE_ITEMS_WEIGHT * f1
    possible = sum(FIELD_WEIGHTS.values()) + LINE_ITEMS_WEIGHT
    return {
        "overall": round(earned / possible, 4),
        "fields": fields,
        "line_items": {"precision": round(p, 3), "recall": round(r, 3), "f1": round(f1, 3)},
    }


def dspy_metric(gold_example, pred, trace=None) -> float:
    """DSPy-compatible metric (so GEPA / optimizers can train against the gold set)."""
    try:
        return score(pred.invoice, gold_example.invoice)["overall"]
    except Exception:
        return 0.0
