# Extraction Benchmark — which architecture performed best

Gold set: **3 invoices** (cargo, uber, wework), scored on field-accuracy (weighted) + line-item F1. Cost is an estimate from public list prices — see `MODELS` in `eval/run.py`.

| Rank | Architecture | Accuracy | Line-item F1 | Latency | Est. $/doc |
|------|--------------|---------:|-------------:|--------:|-----------:|
| 1 | `ocr:gemma-3-12b` | 0.969 | 0.947 | 6.0s | $0.0005 |
| 2 | `vlm:gemma-3-12b` | 0.830 | 0.613 | 6.6s | $0.0006 |

**Best so far:** `ocr:gemma-3-12b` — accuracy 0.969, line-item F1 0.947, ~$0.0005/doc.

## Per-document detail

- **ocr:gemma-3-12b**: cargo 0.94, uber 0.99, wework 1.00
- **vlm:gemma-3-12b**: cargo 0.84, uber 0.75, wework 1.00
