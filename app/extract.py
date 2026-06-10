1"""Extraction orchestration — the model cascade and the three required failure paths.

(a) Output that won't fit the schema -> DSPy raises a parse error -> re-ask once on the
    fast model (DSPy does this internally), then escalate to the premium model; if that
    still fails, the job is marked FAILED (quarantined).
(b) Image-only scans -> routed to the vision model.
(c) Transient API errors -> retried with exponential backoff (deterministic errors are
    NOT retried).
"""
from __future__ import annotations

from datetime import datetime, timezone

import dspy
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.config import settings
from app.documents.loader import load_pdf, png_to_data_uri
from app.llm import client
from app.observability import get_logger
from app.store import JobStore
from app.validation.normalize import normalize_invoice
from app.validation.reconcile import reconcile
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


def run_extraction(*, text: str | None = None, image_uri: str | None = None,
                    premium: bool = False) -> tuple[Invoice, str]:
    """Run extraction. Tier-1 fast model by default, escalating to tier-2 on a schema-parse
    failure. `premium=True` forces the tier-2 model directly (used when a tier-1 result is
    internally inconsistent — see process_job). Returns (invoice, tier_used)."""
    if image_uri is not None:
        predictor, inputs = client.extract_vision, {"page_image": dspy.Image(url=image_uri)}
    else:
        predictor, inputs = client.extract_text, {"document_text": text or ""}

    if premium:
        with dspy.context(lm=client.PREMIUM):
            return _predict(predictor, **inputs), settings.tier2_model
    try:
        return _predict(predictor, **inputs), settings.tier1_model
    except PARSE_ERRORS as exc:  # (a) escalate for quality
        log.warning("schema_parse_failed_escalating", error=str(exc))
        with dspy.context(lm=client.PREMIUM):
            return _predict(predictor, **inputs), settings.tier2_model


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_job(store: JobStore, job_id: str, data: bytes, filename: str | None = None,
                create: bool = False) -> None:
    """Background worker: (create the job row) -> store the raw PDF -> read (text or vision)
    -> extract one invoice -> validate -> persist. One document is one invoice (multi-invoice
    files are split upstream in ingestion).

    The API hands us a pre-generated job id and returns 202 instantly. Live state (status +
    audit) is written to the store's in-memory cache, so the polling UI updates instantly and
    never waits on the serverless SQL warehouse. The single durable write to Delta + the UC
    Volume happens in `store.flush()` at the very end — off the user-facing path.
    """
    def rec(stage: str, detail: str) -> None:
        store.append_audit(job_id, stage, detail)   # live to the cache; flushed to Delta at the end

    if create:
        store.create(filename, job_id=job_id)       # row exists in the cache immediately (no 404 window)
    store.update(job_id, status=JobStatus.RUNNING)
    rec("RUNNING", "extraction started")
    try:
        if filename is None:
            filename = store.get(job_id).filename
        source_path = store.store_document(job_id, filename, data)
        doc = load_pdf(data)
        store.update(job_id, source_path=source_path, was_scan=not doc.has_text)  # one update
        rec("STORED", f"raw PDF retained at {source_path}")

        if doc.has_text:
            rec("READ", "text layer found -> text model")
            inputs = {"text": doc.text}
        else:  # (b) image-only scan / corrupt text layer
            if not doc.page_images_png:
                raise ValueError("scanned PDF produced no renderable pages")
            rec("READ", f"no usable text; {len(doc.page_images_png)} page(s) -> vision model")
            inputs = {"image_uri": png_to_data_uri(doc.page_images_png[0])}

        invoice, tier = run_extraction(**inputs)
        invoice = normalize_invoice(invoice)  # derive aggregate tax from itemized tax lines

        # Correctness check beyond the schema: a well-typed result can still be factually
        # wrong (a weak model misreading amounts). If the line items don't reconcile with the
        # total, escalate to the premium tier; if it still won't reconcile, flag the job for
        # review rather than storing a confident wrong answer (never a silent failure).
        warnings = reconcile(invoice)
        if warnings:
            rec("RECONCILE_WARNING", f"{warnings[0]}; escalating to {settings.tier2_model}")
            try:
                inv2, tier2 = run_extraction(**inputs, premium=True)
                inv2 = normalize_invoice(inv2)
                if not reconcile(inv2):
                    invoice, tier, warnings = inv2, tier2, []
                    rec("ESCALATED", f"premium ({tier2}) reconciled")
            except Exception as exc:  # e.g. a text-only premium tier can't read an image (Free Edition)
                rec("ESCALATION_UNAVAILABLE", f"premium tier could not re-read: {exc}")

        store.update(job_id, status=JobStatus.SUCCEEDED, result=invoice, tier_used=tier, warnings=warnings)
        if warnings:
            rec("FLAGGED_FOR_REVIEW", warnings[0])
            log.warning("job_flagged_for_review", job_id=job_id, warnings=warnings)
        rec("SUCCEEDED",
            f"{invoice.invoice_number or '(no number)'} {invoice.currency or ''} {invoice.total} via {tier}"
            + (" [needs review]" if warnings else ""))
        log.info("job_succeeded", job_id=job_id, tier=tier, flagged=bool(warnings))

    except PARSE_ERRORS as exc:  # (a) still invalid after escalation -> quarantine
        store.update(job_id, status=JobStatus.FAILED, error=f"schema validation failed after escalation: {exc}")
        rec("FAILED", "unparseable output after re-ask + escalation (quarantined)")
        log.warning("job_failed_schema", job_id=job_id, error=str(exc))
    except Exception as exc:  # any other failure -> recorded, never silent
        store.update(job_id, status=JobStatus.FAILED, error=str(exc))
        rec("FAILED", f"error: {exc}")
        log.error("job_failed", job_id=job_id, error=str(exc))
    finally:
        # The UI already reflects the final state from the cache; now persist durably
        # (UC Volume + one Delta job-row INSERT + the audit trail) off the user-facing path.
        store.flush(job_id, data, filename)
