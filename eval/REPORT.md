# Extraction Benchmark — which architecture performed best

Gold set: **3 invoices** (cargo, uber, wework), scored on field-accuracy (weighted) + line-item F1. Cost is an estimate from public list prices — see `MODELS` in `eval/run.py`.

| Rank | Architecture | Accuracy | Line-item F1 | Latency | Est. $/doc |
|------|--------------|---------:|-------------:|--------:|-----------:|
| 1 | `vlm:gemma-3-12b` | 0.870 | 0.807 | 6.9s | $0.0005 |

**Best so far:** `vlm:gemma-3-12b` — accuracy 0.870, line-item F1 0.807, ~$0.0005/doc.

## Per-document detail

- **vlm:gemma-3-12b**: cargo 0.94, uber 0.67, wework 1.00
