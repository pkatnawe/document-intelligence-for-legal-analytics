# Invoice Extraction Service

Extracts header + line-item data from PDF invoices using a Databricks-hosted LLM/VLM,
behind an async (submit → poll) API, with everything persisted to Unity Catalog. This is
**Part 2** of the Document Intelligence case; the platform architecture (Part 1) is in the
working docs under [`docs/`](docs/) (open [`docs/index.html`](docs/index.html)).

**Live on Databricks Apps:** https://invoice-extractor-3508475445691634.aws.databricksapps.com
(behind Databricks OAuth — sign in with a workspace account).

## What it does

1. **Upload UI + async API.** A small web page (served at `/`) and `POST /api/ingest` accept
   a PDF and return **job ids immediately** (HTTP 202) — one per invoice, since a file may
   hold several (the splitter runs at ingestion). Extraction runs on a background worker, so
   user-facing latency is the upload time, not the model time. `GET /api/jobs/{id}` is polled
   for each result, and `GET /api/jobs/{id}/audit` returns the trail. (`POST /api/extract`
   handles a single already-split invoice — used by the CLI.)
2. **Read the document.** Digital PDFs use their text layer; **image-only scans — or a
   corrupt/encoded text layer (common in the real world)** — are rendered to a page image and
   sent to a vision model.
3. **Extract into a typed `Invoice` schema** via DSPy, with a **speed-first model cascade**
   (fast model by default, premium model on escalation).
4. **Persist everything to Unity Catalog:** the job + result in a Delta table, an
   **append-only audit trail**, and the **retained raw PDF in a UC Volume** — the audit
   primitive a Claims team needs.

## One document = one invoice (and the splitter)

The service treats **one PDF as one invoice**. The case dataset, though, is a single PDF
holding **three unrelated invoices** (Uber, WeWork, Cargo — one per page), and none have a
usable text layer. Splitting a multi-invoice file into single-invoice documents is an
**ingestion/preprocessing** concern, kept separate from extraction:
[`app/documents/splitter.py`](app/documents/splitter.py) bursts such a file into one
single-page PDF per page, and each becomes an independent job with its own stored document
and audit trail. See [`scripts/ingest_dataset.py`](scripts/ingest_dataset.py).

## The three required failure cases

| Case | Behaviour | Where |
|------|-----------|-------|
| **(a)** Output won't fit the schema | DSPy re-asks once on the fast model, then escalates to the premium model; still invalid → job `FAILED` (quarantined) | [`app/extract.py`](app/extract.py) |
| **(b)** Image-only scan / corrupt text layer | Detected in `load_pdf`; page rendered to PNG → vision model | [`app/documents/loader.py`](app/documents/loader.py), [`app/extract.py`](app/extract.py) |
| **(c)** Transient API error | Retried with exponential backoff; deterministic errors are **not** retried | [`app/extract.py`](app/extract.py) (`_predict`) |

## Structure

```
app/
├─ documents/loader.py    # text-layer detection + page rendering (case b)
├─ documents/splitter.py  # ingestion preprocess: multi-invoice PDF → single-invoice docs
├─ llm/signatures.py      # DSPy typed signatures (text + vision)
├─ llm/client.py          # DSPy ↔ Databricks serving endpoints; model tiers
├─ validation/schema.py   # Pydantic Invoice — the single source of truth
├─ extract.py             # orchestration: cascade + the three failure paths
├─ store.py               # JobStore Protocol + in-memory test double (no SQLite)
├─ store_delta.py         # Delta + UC Volume store (bound-parameter SQL); the runtime store
├─ observability.py       # structlog + mlflow.dspy.autolog → Databricks experiment
├─ web.py                 # the upload UI (served at /), shows lifecycle + audit trail
└─ api.py                 # FastAPI: POST /api/ingest (split→jobs), /api/extract, GET /api/jobs/{id}[/audit]
app.py                    # entry point (Databricks Apps / local uvicorn)
app.yaml                  # Databricks Apps runtime config
databricks.yml            # Asset Bundle (deploys the App)
scripts/ingest_dataset.py # split the case PDF + drive the API end-to-end
scripts/smoke_test.py     # 60-second check that a serving endpoint is reachable
tests/                    # unit tests: schema, store, splitter, loader, orchestration
```

## Run it — two ways

DSPy needs Python ≥ 3.11. Everything else is in `requirements.txt`.

### 1. Locally (fastest to try)

```bash
conda activate invoice          # Python 3.12 env with dspy, fastapi, etc.
pip install -r requirements.txt
cp .env.example .env             # set DATABRICKS_HOST, DATABRICKS_TOKEN, WAREHOUSE_ID
set -a && source .env && set +a

uvicorn app.api:app --reload --port 8000
# open http://localhost:8000 → drag in a PDF → watch the job, audit trail, and result
```

```bash
# or drive it headless: split the case dataset and run all 3 invoices through the API
PYTHONPATH=. python scripts/ingest_dataset.py
```

Even local runs call the **live** Databricks Foundation Models and write to the **same Delta
tables + UC Volume + MLflow experiment** — no deploy needed to exercise the full flow.

### 2. On Databricks Apps (one command each)

```bash
databricks bundle validate -t dev    # check the config
databricks bundle deploy   -t dev    # upload code + create the App and its secret
databricks bundle run      -t dev invoice_extractor   # start it, print the URL
```

## How deployment works — the Databricks Asset Bundle (DAB)

`databricks.yml` is a **Databricks Asset Bundle** (now also called a *Declarative Automation
Bundle*) — **infrastructure-as-code for Databricks**. Instead of clicking around the UI, the
whole deployable unit is declared in one version-controlled file: the **App**, the **secret**
that injects the token, and **per-environment targets** (`dev`, `prod`). The CLI reconciles
the workspace to that declaration, so a deploy is **reproducible, reviewable, and reversible**.

Why it matters here:

- **Same code, promote by flag.** The identical bundle deploys to the Free-Edition POC
  (`-t dev`) or a paid production workspace (`-t prod`) — only `workspace.host` changes. No
  rewrite, no manual re-clicking, no "works on my workspace."
- **Secrets by reference, never in git.** The PAT lives in a Databricks **secret scope**
  (`invoice_poc/databricks_token`); `databricks.yml` declares it as an app resource and
  `app.yaml` maps it in via `valueFrom`. The value is resolved at runtime by Databricks — it
  is never committed.
- **Auditable deploys.** Every infra change is a Git commit (who/what/when), and `prod` mode
  runs the App as a **service principal** rather than a personal token.

One auth nuance: Databricks Apps auto-inject the app service principal's OAuth, so `app.yaml`
sets `DATABRICKS_AUTH_TYPE=pat` to use the configured PAT and avoid the SDK's "more than one
authorization method" error.

```bash
# put the token into the secret scope once (never committed):
databricks secrets create-scope invoice_poc
databricks secrets put-secret invoice_poc databricks_token --string-value <YOUR_PAT>
```

## Verified end-to-end (2026-06-09)

Run against the case's own dataset on Databricks **Free Edition**, both locally and on the
**deployed App**:

- The dataset is split into 3 single-invoice PDFs; each has **no usable text layer**, so all
  route to the **vision path** (`was_scan = True`).
- Extracted: **Uber** (CA$ ride receipt, 9 line items), **WeWork** (`PXC7PUAWY2HY-1`,
  CA$36.75), **Cargo Collective** (`2011981`, $99 USD).
- Each job, result, retained PDF, and 5-event audit trail (`RECEIVED → RUNNING → STORED →
  READ → SUCCEEDED`) persisted to **`workspace.invoice_poc.jobs` / `.audit_events`** (Delta)
  and the **`documents`** UC Volume; `DESCRIBE HISTORY` shows the versioned who/what/when.

**Free Edition model reality:** the proprietary models (Gemini, Claude) are disabled on Free
Edition (`PERMISSION_DENIED: rate limit of 0`). The POC therefore uses **open-weight** models
Free Edition serves — `gemma-3-12b` (vision), `meta-llama-3-3-70b-instruct` (text). On a paid
workspace the tiers swap back to Gemini/Claude — **same code, one env change** (see
[`.env.example`](.env.example)). Model choice is config, not code. (The open-weight vision
model is imperfect on the noisier receipts — e.g. it may miss an Uber total or read a card
number as an invoice number — which is exactly what the premium tier is for in production.)

## Notes & limitations (POC)

- **Storage:** Delta + UC Volume is the runtime store ([`store_delta.py`](app/store_delta.py));
  SQL uses **bound parameters**, not string interpolation (correct for JSON with embedded
  newlines, and injection-safe). The `JobStore` Protocol is the swap point — at high poll
  volume, job status moves to a transactional store while Delta keeps the append-only audit +
  results. Unit tests run against an in-memory `JobStore` (no SQLite, no live workspace).
- **Scope:** this service handles **PDF invoices**. Multi-format ingestion and document
  classification are platform concerns (see [`docs/`](docs/)), not built here.
- **Version pins:** `dspy.Image` (vision input) and the DSPy parse-error type
  (`AdapterParseError`) can move between DSPy releases — confirm against the installed
  version. `mlflow.dspy.autolog()` is the current tracing call.
