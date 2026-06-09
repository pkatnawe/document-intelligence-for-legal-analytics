"""Drive the running service end-to-end the way ingestion would.

Splits the case dataset (one PDF, three invoices) into single-invoice documents and submits
each to the live API: POST /api/extract returns a job id immediately, then we poll
GET /api/jobs/{id} until each job is terminal. Demonstrates the async contract and the
one-document-one-invoice model against the real FastAPI service.

Run (service must be up — see README):
    PYTHONPATH=. python scripts/ingest_dataset.py
Env: API_BASE (default http://127.0.0.1:8000), PDF_PATH (default case_interview_dataset.pdf)
"""
import os
import time

import requests

from app.documents.splitter import split_pdf

API = os.environ.get("API_BASE", "http://127.0.0.1:8000").rstrip("/")
PDF = os.environ.get("PDF_PATH", "case_interview_dataset.pdf")
# Databricks Apps sit behind OAuth: pass a bearer token via AUTH_TOKEN to reach a deployed app.
HEADERS = {"Authorization": f"Bearer {os.environ['AUTH_TOKEN']}"} if os.environ.get("AUTH_TOKEN") else {}


def submit(name: str, pdf: bytes) -> str:
    r = requests.post(f"{API}/api/extract", files={"file": (name, pdf, "application/pdf")},
                      headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()["job_id"]


def poll(job_id: str, timeout: int = 240) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = requests.get(f"{API}/api/jobs/{job_id}", headers=HEADERS, timeout=30).json()
        if job.get("status") in ("SUCCEEDED", "FAILED"):  # .get(): tolerate the brief pre-INSERT 404 window
            return job
        time.sleep(4)
    return {"status": "TIMEOUT", "id": job_id}


def main() -> None:
    data = open(PDF, "rb").read()
    pages = split_pdf(data)
    base = os.path.splitext(os.path.basename(PDF))[0]
    print(f"split {PDF} -> {len(pages)} single-invoice document(s); submitting to {API}")

    jobs = []
    for sp in pages:
        name = f"{base}_p{sp.index}.pdf"
        jid = submit(name, sp.pdf)
        jobs.append((name, jid))
        print(f"  submitted {name} -> job {jid} (202)")

    print("\npolling for results...")
    for name, jid in jobs:
        job = poll(jid)
        inv = job.get("result") or {}
        print(f"\n[{name}] status={job['status']} was_scan={job.get('was_scan')} tier={job.get('tier_used')}")
        if inv:
            print(f"  vendor={inv.get('vendor')!r} number={inv.get('invoice_number')!r} "
                  f"total={inv.get('currency') or ''}{inv.get('total')} items={len(inv.get('line_items', []))}")
            print(f"  source_path={job.get('source_path')}")
        elif job.get("error"):
            print(f"  error={job['error']}")


if __name__ == "__main__":
    main()
