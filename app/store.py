"""Job store contract + an in-memory test double.

The service persists to **Delta / Unity Catalog** (see `store_delta.DeltaJobStore`): job
status, the extracted result, the retained raw PDF (a UC Volume), and an append-only
`audit_events` table. `JobStore` below is the interface every store implements; the
in-memory `InMemoryJobStore` is a dependency-free double for unit tests, so the test suite
needs no SQLite file and no live workspace.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Optional, Protocol

from app.validation.schema import Job


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore(Protocol):
    def create(self, filename: Optional[str], job_id: Optional[str] = None) -> Job: ...
    def get(self, job_id: str) -> Optional[Job]: ...
    def update(self, job_id: str, **fields) -> None: ...
    def append_audit(self, job_id: str, stage: str, detail: str) -> None: ...
    def append_audit_many(self, job_id: str, events: list[tuple[str, str, str]]) -> None:
        """Append several audit events (ts, stage, detail) in one write."""
        ...
    def get_audit(self, job_id: str) -> list[dict]:
        """Return the append-only audit events for a job, oldest first."""
        ...
    def store_document(self, job_id: str, filename: Optional[str], data: bytes) -> str:
        """Persist the raw uploaded bytes; return the path they were written to."""
        ...

    def flush(self, job_id: str, data: bytes, filename: Optional[str]) -> None:
        """Durably persist a finished job (and its raw PDF) off the request path. A no-op for
        stores that already write durably on each call."""
        ...


class InMemoryJobStore:
    """Dict-backed store for unit tests. Mirrors DeltaJobStore's behaviour, no I/O."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self.audit: list[tuple[str, str, str, str]] = []  # (job_id, ts, stage, detail)
        self.documents: dict[str, bytes] = {}

    def create(self, filename: Optional[str], job_id: Optional[str] = None) -> Job:
        job = Job(id=job_id or str(uuid.uuid4()), filename=filename)
        self._jobs[job.id] = job
        self.append_audit(job.id, "RECEIVED", f"job created for {filename!r}")
        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def update(self, job_id: str, **fields) -> None:
        job = self._jobs[job_id]
        self._jobs[job_id] = job.model_copy(update={**fields, "updated_at": _now()})

    def append_audit(self, job_id: str, stage: str, detail: str) -> None:
        self.audit.append((job_id, _now(), stage, detail))

    def append_audit_many(self, job_id: str, events: list[tuple[str, str, str]]) -> None:
        for ts, stage, detail in events:
            self.audit.append((job_id, ts, stage, detail))

    def get_audit(self, job_id: str) -> list[dict]:
        return [{"ts": ts, "stage": stage, "detail": detail}
                for (jid, ts, stage, detail) in self.audit if jid == job_id]

    def store_document(self, job_id: str, filename: Optional[str], data: bytes) -> str:
        path = f"memory://{job_id}/{filename or 'document.pdf'}"
        self.documents[path] = data
        return path

    def flush(self, job_id: str, data: bytes, filename: Optional[str]) -> None:
        """No-op: the in-memory store is already the durable store (used in tests)."""
        return None


class CachingJobStore:
    """Write-behind cache that makes the UI fast on a serverless SQL warehouse.

    The live job state + audit trail are kept **in memory** (instant reads for the polling
    UI — no warehouse round-trip, no cold-start, no 404 while a row is being INSERTed). The
    slow durable write to Delta + the UC Volume happens **once at the end**, via `flush()`,
    off the user-facing path. So the user sees the result at model speed (~seconds) while
    persistence catches up in the background.

    Reads fall back to the durable store when a job isn't in memory (e.g. after a restart),
    so completed results stay queryable. Trade-off: a job still in-flight during a process
    restart is lost — acceptable at POC volume; production would use a transactional store
    for live status while Delta keeps the durable results + audit trail.
    """

    def __init__(self, durable) -> None:
        self._d = durable
        self._mem = InMemoryJobStore()
        self._lock = threading.Lock()
        # Expose the durable store's table/volume names (the audit endpoint reports them).
        self.jobs = getattr(durable, "jobs", "jobs")
        self.audit = getattr(durable, "audit", "audit_events")
        self.volume_root = getattr(durable, "volume_root", "")

    # --- writes: memory only (instant) ---
    def create(self, filename: Optional[str], job_id: Optional[str] = None) -> Job:
        with self._lock:
            return self._mem.create(filename, job_id=job_id)

    def update(self, job_id: str, **fields) -> None:
        with self._lock:
            self._mem.update(job_id, **fields)

    def append_audit(self, job_id: str, stage: str, detail: str) -> None:
        with self._lock:
            self._mem.append_audit(job_id, stage, detail)

    def append_audit_many(self, job_id: str, events: list[tuple[str, str, str]]) -> None:
        with self._lock:
            self._mem.append_audit_many(job_id, events)

    def store_document(self, job_id: str, filename: Optional[str], data: bytes) -> str:
        # Don't upload yet — just compute the path; the real upload happens in flush().
        return self._d.doc_path(job_id, filename)

    # --- reads: memory first, durable fallback ---
    def get(self, job_id: str) -> Optional[Job]:
        return self._mem.get(job_id) or self._d.get(job_id)

    def get_audit(self, job_id: str) -> list[dict]:
        return self._mem.get_audit(job_id) or self._d.get_audit(job_id)

    # --- the one durable write, off the request path ---
    def flush(self, job_id: str, data: bytes, filename: Optional[str]) -> None:
        job = self._mem.get(job_id)
        if job is None:
            return
        try:
            self._d.store_document(job_id, job.filename or filename, data)  # UC Volume
            self._d.persist(job)                                            # one job-row INSERT
            events = [(e["ts"], e["stage"], e["detail"]) for e in self._mem.get_audit(job_id)]
            self._d.append_audit_many(job_id, events)                       # the whole trail
        except Exception as exc:  # durability is best-effort; the UI result already stands
            from app.observability import get_logger
            get_logger(__name__).warning("durable_flush_failed", job_id=job_id, error=str(exc))
