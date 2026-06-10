# Extraction Benchmark — which architecture performed best

Gold set: **3 invoices** (cargo, uber, wework), scored on field-accuracy (weighted) + line-item F1. Cost is an estimate from public list prices — see `MODELS` in `eval/run.py`.

| Rank | Architecture | Accuracy | Line-item F1 | Latency | Est. $/doc |
|------|--------------|---------:|-------------:|--------:|-----------:|
| 1 | `ocr:gemma-3-12b` | 0.956 | 0.878 | 6.4s | $0.0005 |
| 2 | `vlm:qwen3-vl-8b` | 0.905 | 0.978 | 12.5s | $0.0013 |
| 3 | `ocr:qwen3-vl-8b` | 0.892 | 0.979 | 9.5s | $0.0007 |
| 4 | `vlm:gemma-3-12b` | 0.875 | 0.836 | 6.7s | $0.0006 |

**Best so far:** `ocr:gemma-3-12b` — accuracy 0.956, line-item F1 0.878, ~$0.0005/doc.

## Per-document detail

- **ocr:gemma-3-12b**: cargo 0.94, uber 0.99, wework 0.94
- **vlm:qwen3-vl-8b**: cargo 0.81, uber 1.00, wework 0.88
- **ocr:qwen3-vl-8b**: cargo 0.81, uber 0.80, wework 1.00
- **vlm:gemma-3-12b**: cargo 1.00, uber 0.81, wework 0.88

> Not benchmarked: vlm:qwen3-vl-30b — HF Inference Providers free credits depleted mid-run (HTTP 402), not a quality result. Add a payment method / credits to run.
