from app.store import InMemoryJobStore
from app.validation.schema import Invoice, JobStatus


def test_job_lifecycle():
    store = InMemoryJobStore()
    job = store.create("invoice.pdf")
    assert job.status == JobStatus.PENDING

    store.update(job.id, status=JobStatus.RUNNING, was_scan=False)
    store.update(
        job.id,
        status=JobStatus.SUCCEEDED,
        result=Invoice(invoice_number="INV-9", total=5),
        tier_used="databricks-gemini-3-5-flash",
    )

    got = store.get(job.id)
    assert got is not None
    assert got.status == JobStatus.SUCCEEDED
    assert got.result.invoice_number == "INV-9"
    assert got.tier_used == "databricks-gemini-3-5-flash"
    assert got.was_scan is False


def test_audit_is_append_only():
    store = InMemoryJobStore()
    job = store.create("x.pdf")
    store.append_audit(job.id, "RUNNING", "started")
    events = store.get_audit(job.id)
    stages = [e["stage"] for e in events]
    assert "RECEIVED" in stages and "RUNNING" in stages
    assert all({"ts", "stage", "detail"} <= e.keys() for e in events)


def test_document_is_retained():
    store = InMemoryJobStore()
    job = store.create("scan.pdf")
    path = store.store_document(job.id, "scan.pdf", b"%PDF-1.4 ...")
    assert store.documents[path] == b"%PDF-1.4 ..."
    assert job.id in path


def test_missing_job_returns_none():
    store = InMemoryJobStore()
    assert store.get("does-not-exist") is None
