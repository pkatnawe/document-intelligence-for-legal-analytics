# Benchmark plan — which architecture extracts invoices best (and cheapest)?

The goal is a **structured, evidence-backed answer** to "what setup performed best": not an
opinion, but a scored comparison of the architectures we considered, on a verified gold set,
measuring **accuracy, line-item F1, latency, and cost**.

## The harness (built)
- `gold/*.json` — hand-verified ground truth (see `conventions.md`).
- `harness.py` — loads gold + the rendered page/text; a normalizing metric (field accuracy +
  line-item F1) that also works as a **DSPy metric** so GEPA can optimize against it.
- `run.py` — runs each architecture, writes `results.json` + `REPORT.md`.
- **Baseline today:** `vlm:gemma-3-12b` → accuracy **0.87**, line-item F1 **0.81**, ~7s, ~$0.0005/doc.

## Axis 1 — Reading approach (the OCR vs VLM question)
| Approach | How | Status |
|----------|-----|--------|
| **A. VLM-direct** | render page → vision model reads layout | ✅ running (baseline) |
| **B. OCR-then-text** | Tesseract → text → text model | ⏳ needs `brew install tesseract && pip install pytesseract` |
| **C. Cloud-OCR-then-text** | (optional) a managed OCR → text model | later, if B's quality is layout-limited |

This is the core experiment behind our "classification-guided VLM **over** OCR" decision —
we'll have the numbers to prove (or revise) it: does OCR's layout loss actually cost accuracy
on these invoices, and is the VLM worth its latency/cost?

## Axis 2 — Model (the "stronger model" / cost question)
| Tier | Models | Unlock |
|------|--------|--------|
| Open / cheap | `gemma-3-12b` (vision), `llama-3-3-70b` (text), `qwen2-vl-7b` (vision) | gemma/llama live now; Qwen via a Together/Groq key (`OPENAI_API_KEY` + `OPENAI_BASE_URL`) |
| Premium / escalation | `claude-opus`, `gpt-4o` | `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` |

> **Claude Max ≠ API.** The escalation tier needs an **Anthropic API key** (pay-per-token);
> a Max subscription does not grant programmatic API access. Budget a few $ of API credit, or
> compare Claude manually via claude.ai.

This quantifies the "escalate to a stronger model" claim: **how many more points does the
premium tier buy, and at what $/point** — i.e. is escalation worth it, and on which docs.

## Axis 3 — Reasoning
- `Predict` vs `ChainOfThought` (now CoT). A/B this to confirm CoT's accuracy gain justifies its
  extra tokens/latency.

## Axis 4 — Classification (platform-level) — needs more data
Comparing **rule-based** vs **LLM zero-shot** vs **classification-guided** routing needs a
**multi-type** labelled set (invoices + contracts + emails + minutes). The case dataset is
invoices-only, so this axis is **blocked on data**. Plan: assemble a small multi-type set (a few
public contracts/emails + the invoices), label the type, then measure classification accuracy and
the downstream effect of routing the right type-specific prompt.

## Method
1. Run `run.py` over the full matrix once each axis is unlocked.
2. Rank by accuracy; read cost + latency as the tie-breakers → **accuracy-per-dollar**.
3. Feed the metric to **GEPA** to optimize the winning config's prompt on the gold set, then
   re-score — measuring lift from optimization on top of the best architecture.
4. `REPORT.md` is the deliverable table; `conventions.md` defends the labels.

## What unlocks the rest (checklist)
- [ ] `brew install tesseract && pip install pytesseract` → Axis 1B (OCR path)
- [ ] Anthropic API key → Claude escalation tier
- [ ] Together/Groq (or HF) key + base URL → Qwen, and any other open VLM
- [ ] (optional) move to a **paid workspace** to serve proprietary models through Databricks itself
- [ ] multi-type labelled docs → Axis 4 (classification comparison)
