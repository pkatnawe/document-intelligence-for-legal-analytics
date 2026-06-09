"""CachingJobStore: the UI is served from memory; Delta/Volume are written once, on flush."""
from app.store import CachingJobStore
from app.validation.schema import JobStatus


class FakeDurable:
    """Records every durable call so we can assert the cache only touches Delta on flush."""

    jobs = "cat.sch.jobs"
    audit = "cat.sch.audit_events"
    volume_root = "/Volumes/cat/sch/documents"

    def __init__(self):
        self.calls: list[str] = []
        self.persisted = None
        self.audit_rows: list = []

    def doc_path(self, job_id, filename):
        return f"{self.volume_root}/{job_id}/{filename}"

    def store_document(self, job_id, filename, data):
        self.calls.append("store_document")
        return self.doc_path(job_id, filename)

    def persist(self, job):
        self.calls.append("persist")
        self.persisted = job

    def append_audit_many(self, job_id, events):
        self.calls.append("append_audit_many")
        self.audit_rows = events

    def get(self, job_id):
        return None

    def get_audit(self, job_id):
        return []


def test_writes_stay_in_memory_until_flush():
    durable = FakeDurable()
    store = CachingJobStore(durable)

    job = store.create("invoice.pdf", job_id="j1")
    store.update("j1", status=JobStatus.RUNNING)
    store.append_audit("j1", "READ", "text layer")
    store.store_document("j1", "invoice.pdf", b"%PDF-bytes")

    # Nothing has hit the durable store yet — the UI reads come from memory.
    assert durable.calls == []
    assert store.get("j1").status == JobStatus.RUNNING
    stages = [e["stage"] for e in store.get_audit("j1")]
    assert stages == ["RECEIVED", "READ"]  # create() records RECEIVED


def test_flush_persists_everything_once():
    durable = FakeDurable()
    store = CachingJobStore(durable)
    store.create("invoice.pdf", job_id="j1")
    store.update("j1", status=JobStatus.SUCCEEDED)
    store.append_audit("j1", "SUCCEEDED", "done")

    store.flush("j1", b"%PDF-bytes", "invoice.pdf")

    assert durable.calls == ["store_document", "persist", "append_audit_many"]
    assert durable.persisted.status == JobStatus.SUCCEEDED
    assert [s for (_ts, s, _d) in durable.audit_rows] == ["RECEIVED", "SUCCEEDED"]


def test_read_falls_back_to_durable_after_eviction():
    durable = FakeDurable()
    store = CachingJobStore(durable)
    # A job not in memory (e.g. after a restart) is looked up in the durable store.
    assert store.get("missing") is None  # FakeDurable returns None
    assert store.get_audit("missing") == []
