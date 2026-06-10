"""Routing ablation — cheap OCR for clean docs, VLM for degraded, a rule-based router to pick.

The benchmark showed OCR-then-text wins on CLEAN invoices (cheap + accurate) while the VLM's
value is reading DEGRADED images OCR can't. So the right architecture isn't one reader — it's a
**router**: a cheap signal (Tesseract's per-word OCR confidence) sends clean docs to OCR and
degraded scans to the VLM, keeping cost/latency low and saving the expensive path for where it
actually helps.

This ablation builds a mixed set (each gold invoice in CLEAN and DEGRADED form) and compares:
  - ocr-only   : always OCR -> text model
  - vlm-only   : always image -> vision model
  - router     : OCR-confidence >= threshold -> OCR, else -> VLM
measuring accuracy, cost, latency, and (for the router) which path each doc took.

Run:  PYTHONPATH=. python eval/ablation.py            # gemma both paths (free on Databricks)
      PYTHONPATH=. python eval/ablation.py qwen3-vl-8b  # use a stronger VLM for the VLM path
"""
from __future__ import annotations

import io
import statistics
import sys
import time

import dspy
import pytesseract
from PIL import Image, ImageFilter

from app.documents.loader import load_pdf, png_to_data_uri
from app.llm.signatures import ExtractInvoice, ExtractInvoiceVision
from app.validation.normalize import normalize_invoice
from eval.harness import load_gold, score
from eval.run import MODELS, _build_lm

OCR_CONF_THRESHOLD = 70.0   # mean Tesseract word confidence below this => "degraded" => VLM


def degrade(png: bytes) -> bytes:
    """Simulate a poor phone photo / fax: half-resolution, slight rotation, blur, JPEG q22.
    Returns PNG bytes (JPEG used only to bake in compression artifacts) so the data URI's
    declared image/png type stays correct for the vision endpoint."""
    im = Image.open(io.BytesIO(png)).convert("RGB")
    w, h = im.size
    im = im.resize((max(1, w // 2), max(1, h // 2)))
    im = im.rotate(2, expand=False, fillcolor=(255, 255, 255))
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    jpg = io.BytesIO(); im.save(jpg, format="JPEG", quality=22)      # bake in JPEG artifacts
    out = io.BytesIO(); Image.open(io.BytesIO(jpg.getvalue())).convert("RGB").save(out, format="PNG")
    return out.getvalue()


def ocr_with_conf(png: bytes) -> tuple[str, float]:
    """Return (text, mean per-word confidence) — the cheap routing signal."""
    im = Image.open(io.BytesIO(png))
    data = pytesseract.image_to_data(im, output_type=pytesseract.Output.DICT)
    confs = [int(c) for c in data["conf"] if int(c) >= 0]
    return pytesseract.image_to_string(im), (statistics.mean(confs) if confs else 0.0)


def _tokens(lm):
    u = (lm.history[-1].get("usage") or {}) if lm.history else {}
    return u.get("prompt_tokens", 0), u.get("completion_tokens", 0)


def _extract(path: str, png: bytes, ocr_text: str, lm, vlm_lm, prices):
    """Run one reader; return (invoice, cost, latency)."""
    t = time.time()
    if path == "ocr":
        use, sig, inp = lm, ExtractInvoice, {"document_text": ocr_text}
        pin, pout = prices["ocr"]
    else:
        use, sig, inp = vlm_lm, ExtractInvoiceVision, {"page_image": dspy.Image(url=png_to_data_uri(png))}
        pin, pout = prices["vlm"]
    with dspy.context(lm=use):
        inv = normalize_invoice(dspy.ChainOfThought(sig)(**inp).invoice)
    ti, to = _tokens(use)
    return inv, (ti * pin + to * pout) / 1e6, time.time() - t


def main() -> None:
    vlm_name = sys.argv[1] if len(sys.argv) > 1 else "gemma-3-12b"
    ocr_lm = _build_lm("gemma-3-12b")
    vlm_lm = _build_lm(vlm_name)
    if ocr_lm is None or vlm_lm is None:
        print("missing credentials for gemma-3-12b or", vlm_name); return
    prices = {"ocr": MODELS["gemma-3-12b"][1:3], "vlm": MODELS[vlm_name][1:3]}
    print(f"OCR path: gemma-3-12b (text) | VLM path: {vlm_name} | router threshold: conf>={OCR_CONF_THRESHOLD}\n")

    # Build the mixed set: each invoice clean AND degraded (same gold; the values don't change).
    items = []
    for d in load_gold():
        clean = load_pdf(d._pdf).page_images_png[0]
        items.append((f"{d.name}-clean", clean, d.gold))
        items.append((f"{d.name}-degraded", degrade(clean), d.gold))

    # Precompute OCR text + confidence once per image (the router uses the confidence).
    prepped = [(name, png, gold, *ocr_with_conf(png)) for (name, png, gold) in items]
    print("OCR confidence per document (the routing signal):")
    for name, _png, _g, _txt, conf in prepped:
        tag = "OCR" if conf >= OCR_CONF_THRESHOLD else "VLM"
        print(f"  {name:18} conf={conf:5.1f} -> router picks {tag}")
    print()

    strategies = {
        "ocr-only": lambda conf: "ocr",
        "vlm-only": lambda conf: "vlm",
        "router":   lambda conf: "ocr" if conf >= OCR_CONF_THRESHOLD else "vlm",
    }
    rows = {}
    for sname, choose in strategies.items():
        accs, cost, lat, picks = [], 0.0, 0.0, []
        for name, png, gold, text, conf in prepped:
            path = choose(conf)
            try:
                inv, c, l = _extract(path, png, text, ocr_lm, vlm_lm, prices)
                s = score(inv, gold)["overall"]
            except Exception as exc:
                s, c, l = 0.0, 0.0, 0.0
                print(f"    ! {sname}/{name} error: {str(exc)[:80]}")
            accs.append(s); cost += c; lat += l; picks.append(path)
        rows[sname] = {
            "acc": statistics.mean(accs),
            "acc_clean": statistics.mean([a for a, (n, *_ ) in zip(accs, prepped) if n.endswith("clean")]),
            "acc_degraded": statistics.mean([a for a, (n, *_ ) in zip(accs, prepped) if n.endswith("degraded")]),
            "cost_per_doc": cost / len(prepped),
            "latency_per_doc": lat / len(prepped),
            "vlm_calls": picks.count("vlm"),
        }

    print(f"{'strategy':10} {'acc':>6} {'clean':>7} {'degr':>7} {'$/doc':>9} {'s/doc':>7} {'VLM calls':>10}")
    for s, r in rows.items():
        print(f"{s:10} {r['acc']:6.3f} {r['acc_clean']:7.3f} {r['acc_degraded']:7.3f} "
              f"{r['cost_per_doc']:9.5f} {r['latency_per_doc']:7.1f} {r['vlm_calls']:>10}/{len(prepped)}")


if __name__ == "__main__":
    main()
