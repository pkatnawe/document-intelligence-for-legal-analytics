"""End-to-end live test against Databricks — the full ingestion + extraction flow.

Splits the case dataset (one PDF holding three invoices: Uber, WeWork, Cargo) into three
single-invoice documents, then runs each as an independent job: retain the raw PDF in a UC
Volume, read it, extract on a live serving endpoint, validate, and persist the job + result
+ append-only audit trail to Delta tables in Unity Catalog.

Uses the OpenAI-compatible serving client (the same transport DSPy uses under the hood)
because dspy needs Python 3.11+; the deployed service uses dspy directly. The splitter,
schema, model tiering, failure handling, UC Volume, and the Delta store are the real
service components.

Env: DATABRICKS_HOST, DATABRICKS_TOKEN, WAREHOUSE_ID, [UC_CATALOG], [UC_SCHEMA]
"""
import json
import os

from databricks.sdk import WorkspaceClient

from app.documents.loader import load_pdf, png_to_data_uri
from app.documents.splitter import split_pdf
from app.store_delta import DeltaJobStore
from app.validation.schema import Invoice, JobStatus

WAREHOUSE = os.environ["WAREHOUSE_ID"]
CATALOG = os.environ.get("UC_CATALOG", "workspace")
SCHEMA = os.environ.get("UC_SCHEMA", "invoice_poc")
TIER1 = os.environ.get("TIER1_MODEL", "databricks-gemini-3-5-flash")
TIER2 = os.environ.get("TIER2_MODEL", "databricks-claude-opus-4-8")
PDF = os.environ.get("PDF_PATH", "case_interview_dataset.pdf")

w = WorkspaceClient()
oai = w.serving_endpoints.get_open_ai_client()

SYSTEM = (
    "You extract invoice data. Return ONLY a JSON object that matches this JSON schema "
    "(no prose, no code fences):\n" + json.dumps(Invoice.model_json_schema())
)


def _strip(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1].removeprefix("json").strip()
    return raw


def _call(model: str, content) -> Invoice:
    resp = oai.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}],
        temperature=0,
    )
    return Invoice.model_validate_json(_strip(resp.choices[0].message.content))  # (a) raises on mismatch


def extract(*, text=None, image_uri=None):
    if image_uri:
        content = [
            {"type": "text", "text": "Extract the invoice (header + line items)."},
            {"type": "image_url", "image_url": {"url": image_uri}},
        ]
    else:
        content = f"Extract the invoice (header + line items) from this text:\n{text}"
    try:
        return _call(TIER1, content), TIER1
    except Exception as exc:  # (a) escalate to the premium model
        print(f"    tier-1 ({TIER1}) failed: {exc}\n    -> escalating to {TIER2}")
        return _call(TIER2, content), TIER2


def run_one(store: DeltaJobStore, page_index: int, pdf_bytes: bytes) -> None:
    """One single-invoice document = one independent job."""
    name = f"{os.path.splitext(os.path.basename(PDF))[0]}_p{page_index}.pdf"
    job = store.create(name)
    print(f"\n=== page {page_index} -> job {job.id} ({name}) ===")

    store.update(job.id, status=JobStatus.RUNNING)
    store.append_audit(job.id, "RUNNING", "extraction started")

    source_path = store.store_document(job.id, name, pdf_bytes)
    store.update(job.id, source_path=source_path)
    store.append_audit(job.id, "STORED", f"raw PDF retained at {source_path}")

    doc = load_pdf(pdf_bytes)
    store.update(job.id, was_scan=not doc.has_text)
    if doc.has_text:
        store.append_audit(job.id, "READ", "usable text layer -> text model")
        invoice, tier = extract(text=doc.text)
    else:
        store.append_audit(job.id, "READ", f"no usable text -> vision model ({len(doc.page_images_png)} page(s))")
        invoice, tier = extract(image_uri=png_to_data_uri(doc.page_images_png[0]))

    store.update(job.id, status=JobStatus.SUCCEEDED, result=invoice, tier_used=tier)
    store.append_audit(job.id, "SUCCEEDED", f"{invoice.invoice_number or '(no number)'} {invoice.total} via {tier}")

    got = store.get(job.id)
    print(f"  vendor={got.result.vendor!r} number={got.result.invoice_number!r} "
          f"total={got.result.currency or ''}{got.result.total} tier={got.tier_used} was_scan={got.was_scan}")
    print(f"  source_path={got.source_path}")


def main():
    data = open(PDF, "rb").read()
    store = DeltaJobStore(WAREHOUSE, CATALOG, SCHEMA)

    pages = split_pdf(data)  # ingestion preprocess: one PDF of 3 invoices -> 3 documents
    print(f"split {PDF} into {len(pages)} single-invoice document(s)")
    for sp in pages:
        run_one(store, sp.index, sp.pdf)

    print("\n--- read back all jobs from Delta (Unity Catalog) ---")
    rows = store._exec(
        f"SELECT filename, status, was_scan, tier_used FROM {store.jobs} ORDER BY created_at DESC "
        f"LIMIT {len(pages)}", fetch=True,
    )
    for r in rows:
        print(f"  {r[0]:<28} status={r[1]} was_scan={r[2]} tier={r[3]}")
    print(f"\nDelta tables: {store.jobs} , {store.audit}  |  Volume: {store.volume_root}")


if __name__ == "__main__":
    main()
