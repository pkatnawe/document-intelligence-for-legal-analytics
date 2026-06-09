"""Job store contract + an in-memory test double.

The service persists to **Delta / Unity Catalog** (see `store_delta.DeltaJobStore`): job
status, the extracted result, the retained raw PDF (a UC Volume), and an append-only
`audit_events` table. `JobStore` below is the interface every store implements; the
in-memory `InMemoryJobStore` is a dependency-free double for unit tests, so the test suite
needs no SQLite file and no live workspace.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Protocol

from app.validation.schema import Job


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JobStore(Protocol):
    def create(self, filename: Optional[str]) -> Job: ...
    def get(self, job_id: str) -> Optional[Job]: ...
    def update(self, job_id: str, **fields) -> None: ...
    def append_audit(self, job_id: str, stage: str, detail: str) -> None: ...
    def get_audit(self, job_id: str) -> list[dict]:
        """Return the append-only audit events for a job, oldest first."""
        ...
    def store_document(self, job_id: str, filename: Optional[str], data: bytes) -> str:
        """Persist the raw uploaded bytes; return the path they were written to."""
        ...


class InMemoryJobStore:
    """Dict-backed store for unit tests. Mirrors DeltaJobStore's behaviour, no I/O."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self.audit: list[tuple[str, str, str, str]] = []  # (job_id, ts, stage, detail)
        self.documents: dict[str, bytes] = {}

    def create(self, filename: Optional[str]) -> Job:
        job = Job(id=str(uuid.uuid4()), filename=filename)
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

    def get_audit(self, job_id: str) -> list[dict]:
        return [{"ts": ts, "stage": stage, "detail": detail}
                for (jid, ts, stage, detail) in self.audit if jid == job_id]

    def store_document(self, job_id: str, filename: Optional[str], data: bytes) -> str:
        path = f"memory://{job_id}/{filename or 'document.pdf'}"
        self.documents[path] = data
        return path
