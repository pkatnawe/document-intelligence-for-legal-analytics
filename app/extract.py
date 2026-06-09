"""Extraction orchestration — the model cascade and the three required failure paths.

(a) Output that won't fit the schema -> DSPy raises a parse error -> re-ask once on the
    fast model (DSPy does this internally), then escalate to the premium model; if that
    still fails, the job is marked FAILED (quarantined).
(b) Image-only scans -> routed to the vision model.
(c) Transient API errors -> retried with exponential backoff (deterministic errors are
    NOT retried).
"""
from __future__ import annotations

import dspy
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.documents.loader import load_pdf, png_to_data_uri
from app.llm import client
from app.observability import get_logger
from app.store import JobStore
from app.validation.schema import Invoice, JobStatus

log = get_logger(__name__)

# (a) DSPy raises its own parse error when the LM output can't be coerced to the schema.
try:
    from dspy.utils.exceptions import AdapterParseError

    PARSE_ERRORS: tuple = (AdapterParseError,)
except Exception:  # version safety
    PARSE_ERRORS = ()

# (c) Transient errors worth retrying. Deterministic errors (e.g. parse) are excluded.
try:
    import openai

    TRANSIENT_ERRORS: tuple = (
        openai.APIConnectionError,
        openai.APITimeoutError,
        openai.RateLimitError,
        openai.InternalServerError,
    )
except Exception:  # version safety
    TRANSIENT_ERRORS = ()


def _predict(predictor, **inputs) -> Invoice:
    """Call a predictor, retrying only on transient errors (failure case (c))."""

    @retry(
        retry=retry_if_exception_type(TRANSIENT_ERRORS) if TRANSIENT_ERRORS else retry_if_exception_type(()),
        stop=stop_after_attempt(settings.max_attempts),
        wait=wait_exponential(min=1, max=10),
        reraise=True,
    )
    def _call() -> Invoice:
        return predictor(**inputs).invoice

    return _call()


def run_extraction(*, text: str | None = None, image_uri: str | None = None) -> tuple[Invoice, str]:
    """Run the cascade: tier-1 fast model, escalating to tier-2 on a schema-parse failure.

    Returns (invoice, tier_used). A parse failure on the premium model propagates to the
    caller, which quarantines the job.
    """
    if image_uri is not None:
        predictor, inputs = client.extract_vision, {"page_image": dspy.Image(url=image_uri)}
    else:
        predictor, inputs = client.extract_text, {"document_text": text or ""}

    try:
        return _predict(predictor, **inputs), settings.tier1_model
    except PARSE_ERRORS as exc:  # (a) escalate for quality
        log.warning("schema_parse_failed_escalating", error=str(exc))
        with dspy.context(lm=client.PREMIUM):
            return _predict(predictor, **inputs), settings.tier2_model


def process_job(store: JobStore, job_id: str, data: bytes) -> None:
    """Background worker: store the raw PDF -> read (text or vision) -> extract one invoice
    -> validate -> persist. One document is one invoice (multi-invoice files are split
    upstream in ingestion)."""
    store.update(job_id, status=JobStatus.RUNNING)
    store.append_audit(job_id, "RUNNING", "extraction started")
    try:
        filename = store.get(job_id).filename
        source_path = store.store_document(job_id, filename, data)
        store.update(job_id, source_path=source_path)
        store.append_audit(job_id, "STORED", f"raw PDF retained at {source_path}")

        doc = load_pdf(data)
        store.update(job_id, was_scan=not doc.has_text)

        if doc.has_text:
            store.append_audit(job_id, "READ", "text layer found -> text model")
            invoice, tier = run_extraction(text=doc.text)
        else:  # (b) image-only scan / corrupt text layer
            n = len(doc.page_images_png)
            store.append_audit(job_id, "READ", f"no usable text; {n} page(s) -> vision model")
            if not doc.page_images_png:
                raise ValueError("scanned PDF produced no renderable pages")
            invoice, tier = run_extraction(image_uri=png_to_data_uri(doc.page_images_png[0]))

        store.update(job_id, status=JobStatus.SUCCEEDED, result=invoice, tier_used=tier)
        store.append_audit(
            job_id, "SUCCEEDED",
            f"{invoice.invoice_number or '(no number)'} {invoice.currency or ''} {invoice.total} via {tier}",
        )
        log.info("job_succeeded", job_id=job_id, tier=tier)

    except PARSE_ERRORS as exc:  # (a) still invalid after escalation -> quarantine
        store.update(job_id, status=JobStatus.FAILED, error=f"schema validation failed after escalation: {exc}")
        store.append_audit(job_id, "FAILED", "unparseable output after re-ask + escalation (quarantined)")
        log.warning("job_failed_schema", job_id=job_id, error=str(exc))
    except Exception as exc:  # any other failure -> recorded, never silent
        store.update(job_id, status=JobStatus.FAILED, error=str(exc))
        store.append_audit(job_id, "FAILED", f"error: {exc}")
        log.error("job_failed", job_id=job_id, error=str(exc))
