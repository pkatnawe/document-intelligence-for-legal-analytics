# Extraction Benchmark — which architecture performed best

Gold set: **3 invoices** (cargo, uber, wework), scored on field-accuracy (weighted) + line-item F1. Cost is an estimate from public list prices — see `MODELS` in `eval/run.py`.

| Rank | Architecture | Accuracy | Line-item F1 | Latency | Est. $/doc |
|------|--------------|---------:|-------------:|--------:|-----------:|
| 1 | `ocr:gemma-3-12b` | 0.957 | 0.881 | 6.1s | $0.0005 |
| 2 | `ocr:llama-3-3-70b` | 0.884 | 0.883 | 7.9s | $0.0012 |
| 3 | `vlm:gemma-3-12b` | 0.868 | 0.850 | 7.0s | $0.0006 |

**Best so far:** `ocr:gemma-3-12b` — accuracy 0.957, line-item F1 0.881, ~$0.0005/doc.

## Per-document detail

- **ocr:gemma-3-12b**: cargo 0.94, uber 0.99, wework 0.94
- **ocr:llama-3-3-70b**: cargo 0.81, uber 0.87, wework 1.00
- **vlm:gemma-3-12b**: cargo 0.94, uber 0.75, wework 0.88
