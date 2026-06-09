"""FastAPI service — the async extraction contract.

POST /api/extract  -> accepts a PDF, returns a job id immediately (HTTP 202).
GET  /api/jobs/{id} -> returns job status, and the result once complete.
GET  /              -> health check.

The slow extraction runs on a background worker, so user-facing latency is the time to
accept the upload, not the time to extract. Routes are under /api for Databricks Apps
OAuth compatibility.
"""
from __future__ import annotations

import os

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse

from app.config import settings
from app.extract import process_job
from app.llm import client
from app.observability import configure as configure_logging
from app.observability import get_logger
from app.store_delta import DeltaJobStore
from app.web import UPLOAD_PAGE

log = get_logger(__name__)
app = FastAPI(title="Invoice Extraction Service", version="1.0")


def _make_store() -> DeltaJobStore:
    """The runtime store is Delta / Unity Catalog. Jobs, the append-only audit trail, and
    the retained raw PDFs all live in one UC schema; nothing is kept on local disk."""
    warehouse, catalog = os.environ.get("WAREHOUSE_ID"), os.environ.get("UC_CATALOG")
    if not (warehouse and catalog):
        raise RuntimeError(
            "Delta store not configured: set WAREHOUSE_ID and UC_CATALOG (see .env.example). "
            "On Databricks Apps these come from the app resources."
        )
    return DeltaJobStore(warehouse, catalog, os.environ.get("UC_SCHEMA", "invoice_poc"))


store = _make_store()


@app.on_event("startup")
def _startup() -> None:
    configure_logging()
    client.configure()
    log.info("service_started", tier1=settings.tier1_model, tier2=settings.tier2_model)


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    """A minimal upload UI. The app sits behind Databricks OAuth, so the browser session is
    already authenticated and the page's same-origin calls to /api need no token."""
    return UPLOAD_PAGE


@app.get("/healthz")
def health() -> dict:
    return {"status": "ok", "service": "invoice-extraction"}


@app.post("/api/extract", status_code=202)
async def submit(file: UploadFile, bg: BackgroundTasks) -> dict:
    """Accept a PDF and return a job id immediately; extraction runs in the background."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="empty file")
    job = store.create(filename=file.filename)
    bg.add_task(process_job, store, job.id, data)
    return {"job_id": job.id, "status": job.status.value}


@app.get("/api/jobs/{job_id}")
def status(job_id: str) -> dict:
    """Poll a job. Returns status, and the extracted invoice once SUCCEEDED."""
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.model_dump()


@app.get("/api/jobs/{job_id}/audit")
def audit(job_id: str) -> dict:
    """The append-only audit trail for a job: every state change, oldest first, plus where
    the artifacts are stored (UC Volume + Delta tables)."""
    if store.get(job_id) is None:
        raise HTTPException(status_code=404, detail="job not found")
    return {
        "job_id": job_id,
        "events": store.get_audit(job_id),
        "stored_in": {"jobs_table": store.jobs, "audit_table": store.audit, "volume": store.volume_root},
    }
