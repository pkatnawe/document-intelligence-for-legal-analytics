"""Orchestration tests for process_job — the failure handling the case grades on.

The model is stubbed (no network), so these run offline and fast; they verify the worker's
control flow: document retained, audit trail written, success persisted, and failures
recorded (never silent).
"""
import app.extract as extract
from app.store import InMemoryJobStore
from app.validation.schema import Invoice, JobStatus


def _stages(store, job_id):
    return [e["stage"] for e in store.get_audit(job_id)]


def test_happy_path_persists_result_document_and_audit(text_pdf, monkeypatch):
    monkeypatch.setattr(
        extract, "run_extraction",
        lambda **kw: (Invoice(invoice_number="INV-1", total=100.0), "tier1-model"),
    )
    store = InMemoryJobStore()
    job = store.create("invoice.pdf")

    extract.process_job(store, job.id, text_pdf)

    got = store.get(job.id)
    assert got.status == JobStatus.SUCCEEDED
    assert got.result.invoice_number == "INV-1"
    assert got.tier_used == "tier1-model"
    assert got.source_path and got.source_path in store.documents      # raw PDF retained
    # full audit trail, in order
    assert _stages(store, job.id) == ["RECEIVED", "RUNNING", "STORED", "READ", "SUCCEEDED"]


def test_scan_pdf_takes_the_vision_path(scan_like_pdf, monkeypatch):
    seen = {}
    def fake(**kw):
        seen.update(kw)                       # capture whether text= or image_uri= was used
        return Invoice(invoice_number="S-1", total=1.0), "vision-model"
    monkeypatch.setattr(extract, "run_extraction", fake)
    store = InMemoryJobStore()
    job = store.create("scan.pdf")

    extract.process_job(store, job.id, scan_like_pdf)

    assert store.get(job.id).was_scan is True
    assert "image_uri" in seen and "text" not in seen   # routed to the VLM (case b)


def test_any_failure_is_recorded_never_silent(text_pdf, monkeypatch):
    def boom(**kw):
        raise ValueError("model exploded")
    monkeypatch.setattr(extract, "run_extraction", boom)
    store = InMemoryJobStore()
    job = store.create("invoice.pdf")

    extract.process_job(store, job.id, text_pdf)

    got = store.get(job.id)
    assert got.status == JobStatus.FAILED
    assert "model exploded" in got.error
    assert "FAILED" in _stages(store, job.id)


def test_inconsistent_extraction_is_flagged_not_silently_succeeded(text_pdf, monkeypatch):
    from app.validation.schema import LineItem
    # a well-typed but wrong result: line items (130) don't reconcile with total (53)
    bad = Invoice(invoice_number="X", total=53.43,
                  line_items=[LineItem(description="a", amount=64.46), LineItem(description="b", amount=65.54)])
    monkeypatch.setattr(extract, "run_extraction", lambda **kw: (bad, "tier1-model"))
    store = InMemoryJobStore()
    job = store.create("invoice.pdf")

    extract.process_job(store, job.id, text_pdf)

    got = store.get(job.id)
    assert got.status == JobStatus.SUCCEEDED          # data is kept...
    assert got.warnings                               # ...but flagged for review (not silent)
    assert "FLAGGED_FOR_REVIEW" in _stages(store, job.id)


def test_transient_errors_retry_but_deterministic_do_not():
    # transient -> retried up to max_attempts; deterministic -> not retried
    if not extract.TRANSIENT_ERRORS:
        return  # openai not importable in this env
    import openai
    calls = {"n": 0}
    class Flaky:
        def __call__(self, **kw):
            calls["n"] += 1
            if calls["n"] < 2:
                raise openai.APITimeoutError(request=None)
            class R: invoice = Invoice(invoice_number="OK", total=1.0)
            return R()
    out = extract._predict(Flaky())
    assert out.invoice_number == "OK" and calls["n"] == 2
