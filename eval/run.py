"""Benchmark runner — compare architectures on the gold set and write a structured report.

Each *config* is one architecture: a reading approach (VLM-direct vs OCR-then-text) x a model.
For every config we run all gold invoices, score them with the harness metric, and record
accuracy, line-item F1, latency, and (estimated) cost. The output is eval/results.json plus a
human-readable eval/REPORT.md table — the "what setup performed best" deliverable.

Run:   PYTHONPATH=. python eval/run.py                 # all available configs
       PYTHONPATH=. python eval/run.py vlm:gemma-3-12b  # a subset by name

Adding a model is one line in MODELS; adding a provider key unlocks its configs automatically.
"""
from __future__ import annotations

import io
import json
import os
import sys
import time
from pathlib import Path

import dspy

from eval.harness import load_gold, score

OUT = Path(__file__).parent

# --- model registry: name -> (litellm id, in $/1M tokens, out $/1M tokens, vision?) ---
# Prices are public list prices as of 2026-06; refine per your contract. Databricks open
# models are billed in DBUs — the $ here is an approximation for relative comparison.
MODELS = {
    "gemma-3-12b":   ("databricks/databricks-gemma-3-12b",                0.20, 0.20, True),
    "llama-3-3-70b": ("databricks/databricks-meta-llama-3-3-70b-instruct", 0.50, 0.50, False),
    # Unlock by setting the provider's key; vision flag gates the VLM reader.
    "qwen2-vl-7b":   ("openai/Qwen/Qwen2-VL-7B-Instruct",                 0.20, 0.20, True),    # via TOGETHER/GROQ base_url
    "claude-opus":   ("anthropic/claude-opus-4-8",                       15.00, 75.00, True),
    "gpt-4o":        ("openai/gpt-4o",                                    2.50, 10.00, True),
}


def _build_lm(name: str):
    """Build a dspy.LM for a model name, or return None if its credentials are absent."""
    lid, _, _, _ = MODELS[name]
    if lid.startswith("databricks/"):
        if not os.environ.get("DATABRICKS_API_BASE") or not os.environ.get("DATABRICKS_API_KEY"):
            base = os.environ.get("DATABRICKS_HOST")
            if base and os.environ.get("DATABRICKS_TOKEN"):
                os.environ["DATABRICKS_API_BASE"] = f"{base}/serving-endpoints"
                os.environ["DATABRICKS_API_KEY"] = os.environ["DATABRICKS_TOKEN"]
            else:
                return None
        return dspy.LM(lid, cache=False)
    if lid.startswith("anthropic/"):
        return dspy.LM(lid, cache=False) if os.environ.get("ANTHROPIC_API_KEY") else None
    if lid.startswith("openai/"):
        # Either real OpenAI, or an OpenAI-compatible host (Together/Groq/HF) via OPENAI_BASE_URL.
        return dspy.LM(lid, cache=False) if os.environ.get("OPENAI_API_KEY") else None
    return None


def _ocr_text(png: bytes) -> str | None:
    try:
        import pytesseract
        from PIL import Image
        return pytesseract.image_to_string(Image.open(io.BytesIO(png)))
    except Exception:
        return None


def _run_config(reader: str, model_name: str, docs) -> dict | None:
    from app.llm.signatures import ExtractInvoice, ExtractInvoiceVision

    lid, in_price, out_price, vision = MODELS[model_name]
    if reader == "vlm" and not vision:
        return None  # text-only model can't do the vision reader
    lm = _build_lm(model_name)
    if lm is None:
        return None  # credentials missing -> skipped

    predictor = (dspy.ChainOfThought(ExtractInvoiceVision) if reader == "vlm"
                 else dspy.ChainOfThought(ExtractInvoice))
    rows, lat, tin, tout = [], [], 0, 0
    with dspy.context(lm=lm):
        for d in docs:
            if reader == "vlm":
                inputs = {"page_image": dspy.Image(url=d.image_uri)}
            else:
                text = d.text or _ocr_from_doc(d)
                if not text:
                    return {"skipped": "no OCR engine (pip install pytesseract + brew install tesseract)"}
                inputs = {"document_text": text}
            t = time.time()
            try:
                pred = predictor(**inputs).invoice
                sc = score(pred, d.gold)
            except Exception as exc:
                sc = {"overall": 0.0, "fields": {}, "line_items": {"f1": 0.0}, "error": str(exc)[:120]}
            lat.append(time.time() - t)
            u = (lm.history[-1].get("usage") or {}) if lm.history else {}
            tin += u.get("prompt_tokens", 0); tout += u.get("completion_tokens", 0)
            rows.append({"doc": d.name, **sc})

    n = len(rows)
    cost = (tin * in_price + tout * out_price) / 1e6
    return {
        "reader": reader, "model": model_name, "config": f"{reader}:{model_name}",
        "overall": round(sum(r["overall"] for r in rows) / n, 4),
        "line_item_f1": round(sum(r["line_items"]["f1"] for r in rows) / n, 4),
        "avg_latency_s": round(sum(lat) / n, 2),
        "tokens": {"in": tin, "out": tout},
        "est_cost_per_doc": round(cost / n, 6),
        "per_doc": rows,
    }


def _ocr_from_doc(d) -> str | None:
    from app.documents.loader import load_pdf
    doc = load_pdf(d._pdf)
    return _ocr_text(doc.page_images_png[0]) if doc.page_images_png else None


def main() -> None:
    docs = load_gold()
    print(f"gold set: {len(docs)} invoices ({', '.join(d.name for d in docs)})")

    wanted = set(sys.argv[1:])
    configs = [(r, m) for m in MODELS for r in ("vlm", "ocr")]
    if wanted:
        configs = [(r, m) for (r, m) in configs if f"{r}:{m}" in wanted]

    results = []
    for reader, model in configs:
        res = _run_config(reader, model, docs)
        if res is None:
            print(f"  - skip {reader}:{model} (no credentials / incompatible)")
            continue
        if res.get("skipped"):
            print(f"  - skip {reader}:{model} ({res['skipped']})")
            continue
        print(f"  ✓ {res['config']:24} acc={res['overall']:.3f}  "
              f"items_f1={res['line_item_f1']:.3f}  {res['avg_latency_s']:.1f}s  "
              f"${res['est_cost_per_doc']:.4f}/doc")
        results.append(res)

    results.sort(key=lambda r: r["overall"], reverse=True)
    (OUT / "results.json").write_text(json.dumps(results, indent=2))
    _write_report(results, docs)
    print(f"\nwrote {OUT/'results.json'} and {OUT/'REPORT.md'}")


def _write_report(results, docs) -> None:
    lines = ["# Extraction Benchmark — which architecture performed best",
             "",
             f"Gold set: **{len(docs)} invoices** ({', '.join(d.name for d in docs)}), "
             "scored on field-accuracy (weighted) + line-item F1. Cost is an estimate from "
             "public list prices — see `MODELS` in `eval/run.py`.",
             "",
             "| Rank | Architecture | Accuracy | Line-item F1 | Latency | Est. $/doc |",
             "|------|--------------|---------:|-------------:|--------:|-----------:|"]
    for i, r in enumerate(results, 1):
        lines.append(f"| {i} | `{r['config']}` | {r['overall']:.3f} | {r['line_item_f1']:.3f} "
                     f"| {r['avg_latency_s']:.1f}s | ${r['est_cost_per_doc']:.4f} |")
    if results:
        best = results[0]
        lines += ["", f"**Best so far:** `{best['config']}` — accuracy {best['overall']:.3f}, "
                  f"line-item F1 {best['line_item_f1']:.3f}, ~${best['est_cost_per_doc']:.4f}/doc.",
                  "", "## Per-document detail", ""]
        for r in results:
            lines.append(f"- **{r['config']}**: " + ", ".join(
                f"{p['doc']} {p['overall']:.2f}" for p in r["per_doc"]))
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
