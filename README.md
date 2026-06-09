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

## Structure — mapped to the case's "clear separation" requirement

The brief asks for *"a proper backend component with clear separation between document
handling, LLM interaction, and output validation."* That is the layout — **each concern is
its own package, and no concern leaks into another** (verified by imports):

```
app/
│  ── ① DOCUMENT HANDLING ──  (only bytes + PyMuPDF; no model, no schema)
├─ documents/loader.py     # text-layer detection; render scans to images (case b)
├─ documents/splitter.py   # ingestion preprocess: multi-invoice PDF → single-invoice docs
│
│  ── ② LLM INTERACTION ──  (the only place a model is ever called)
├─ llm/signatures.py       # DSPy typed signatures: declared inputs → Invoice output
├─ llm/client.py           # wires DSPy to Databricks endpoints; the fast/premium tiers
│
│  ── ③ OUTPUT VALIDATION ──  (pure Pydantic; no model, no I/O)
├─ validation/schema.py    # the Invoice contract — the single source of truth
│
│  ── orchestration + platform (wire the three together; don't mix them) ──
├─ extract.py              # the cascade + the three failure paths (a/b/c)
├─ store.py / store_delta.py  # JobStore Protocol → Delta + UC Volume + audit (runtime)
├─ observability.py        # structlog + mlflow.dspy.autolog → Databricks experiment
├─ web.py                  # the upload UI served at /
└─ api.py                  # FastAPI: POST /api/ingest, /api/extract, GET /api/jobs/{id}[/audit]
app.py / app.yaml / databricks.yml   # entry point · Apps runtime config · Asset Bundle
scripts/ingest_dataset.py  # split the case PDF + drive the API end-to-end
scripts/smoke_test.py      # 60-second check that a serving endpoint is reachable
tests/                     # schema · store · splitter · loader · orchestration (20 tests)
```

### How the separation actually holds

The three concerns never touch each other directly — they only meet inside the orchestrator,
which calls each in turn:

```
process_job(extract.py):
   bytes ──▶ ① load_pdf(data)              # document handling: is there text? else render image
         ──▶ ② run_extraction(text|image)  # LLM interaction: DSPy calls the tiered model
         ──▶ ③ returns a validated Invoice # output validation: enforced at the DSPy boundary
         ──▶ persist (store) + audit
```

- **① Document handling** (`documents/`) imports only `fitz` — it decides text-vs-vision and
  never knows what a model or a schema is.
- **② LLM interaction** (`llm/`) is the *only* code that talks to a model. Swapping the model
  tier is one line in `client.py`; nothing else changes.
- **③ Validation is structural, not hand-rolled.** The DSPy signature declares its output type
  as the Pydantic `Invoice`, so DSPy coerces the model's output to that schema and raises
  `AdapterParseError` if it doesn't fit — that *is* failure case (a). There is no bespoke
  JSON-parsing/validation code to drift; the schema is the contract.

The **DSPy typed signature is the deliberate seam** between ② and ③: it is simultaneously the
model interface (declared inputs) and the validation contract (the `Invoice` output type), so
the two layers connect at exactly one typed boundary. The orchestrator (`extract.py`) only
sequences the steps and handles failures — it contains no PDF parsing and defines no schema.

The brief's other two Task-2 asks are covered the same structural way:

- **A proper backend, not a script/notebook.** It's an installable package (`app/`) behind a
  FastAPI service with a swappable `JobStore` interface and a unit-test suite — runnable
  locally (`uvicorn`) or deployed unchanged to Databricks Apps.
- **Structured logging at key steps.** Two layers, both machine-queryable: `observability.py`
  emits JSON logs via `structlog`, and every processing step writes an append-only **audit
  event** (`RECEIVED → RUNNING → STORED → READ → SUCCEEDED/FAILED`) to Delta — so "what
  happened to this document" is a query, not a grep.

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
