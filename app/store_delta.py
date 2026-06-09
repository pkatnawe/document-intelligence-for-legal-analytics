"""Delta-backed JobStore for Databricks (Unity Catalog) — the only runtime store.

Everything a Claims auditor needs lives in one Unity Catalog schema:
  * `jobs`          — one row per extraction (status, result JSON, tier used, source path)
  * `audit_events`  — append-only who/what/when trail of every state change
  * `documents`     — a UC **Volume** holding the retained raw PDF for each job

Table writes go through the Databricks **Statement Execution API** and the raw PDF through
the **Files API** (both via the databricks-sdk on a serverless SQL warehouse) — pure
Python, no heavyweight connector. This implements the `JobStore` interface, so the service
code is storage-agnostic.

All values are passed as **bound parameters** (`:name`), never inlined into the SQL text.
That is both injection-safe and correct: Spark SQL string literals interpret backslash
escapes, so inlining a JSON string (e.g. an address with an embedded newline) would corrupt
it on the round-trip. Parameters round-trip values verbatim.

Note: Delta UPDATEs on job status are fine at POC volume; at high poll volume job status
would move to a transactional store while Delta keeps the append-only audit + results.
"""
from __future__ import annotations

import io
import uuid
from datetime import datetime, timezone
from typing import Optional

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem

from app.validation.schema import Invoice, Job, JobStatus


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _as_bool(value) -> Optional[bool]:
    if value is None:
        return None
    return str(value).lower() == "true"


def _params(values: dict[str, object]) -> list[StatementParameterListItem]:
    """Turn a {name: value} dict into bound SQL parameters. None -> typed SQL NULL;
    bool -> BOOLEAN; everything else -> STRING."""
    items: list[StatementParameterListItem] = []
    for name, value in values.items():
        if value is None:
            items.append(StatementParameterListItem(name=name, value=None, type="STRING"))
        elif isinstance(value, bool):
            items.append(StatementParameterListItem(name=name, value=str(value).lower(), type="BOOLEAN"))
        else:
            items.append(StatementParameterListItem(name=name, value=str(value), type="STRING"))
    return items


class DeltaJobStore:
    def __init__(self, warehouse_id: str, catalog: str, schema: str,
                 workspace: Optional[WorkspaceClient] = None) -> None:
        self._w = workspace or WorkspaceClient()
        self._wh = warehouse_id
        self._catalog, self._schema = catalog, schema
        self.jobs = f"{catalog}.{schema}.jobs"
        self.audit = f"{catalog}.{schema}.audit_events"
        self.volume = f"{catalog}.{schema}.documents"
        self.volume_root = f"/Volumes/{catalog}/{schema}/documents"
        self._exec(f"CREATE SCHEMA IF NOT EXISTS {catalog}.{schema}")
        self._exec(
            f"""CREATE TABLE IF NOT EXISTS {self.jobs}(
                  id STRING, status STRING, filename STRING, created_at STRING, updated_at STRING,
                  was_scan BOOLEAN, source_path STRING, tier_used STRING,
                  result_json STRING, error STRING) USING DELTA"""
        )
        self._exec(
            f"""CREATE TABLE IF NOT EXISTS {self.audit}(
                  event_id STRING, job_id STRING, ts STRING, stage STRING, detail STRING) USING DELTA"""
        )
        # UC Volume that retains the original uploaded PDF for each job (legal audit trail).
        self._exec(f"CREATE VOLUME IF NOT EXISTS {self.volume}")

    def _exec(self, statement: str, params: Optional[dict] = None, fetch: bool = False):
        import time

        r = self._w.statement_execution.execute_statement(
            warehouse_id=self._wh, statement=statement, wait_timeout="30s",
            parameters=_params(params) if params else None,
        )
        # Serverless warehouses cold-start; poll until the statement reaches a terminal state.
        deadline = time.time() + 180
        while (r.status and r.status.state and r.status.state.value in ("PENDING", "RUNNING")
               and time.time() < deadline):
            time.sleep(2)
            r = self._w.statement_execution.get_statement(r.statement_id)
        state = r.status.state.value if (r.status and r.status.state) else "UNKNOWN"
        if state != "SUCCEEDED":
            err = getattr(r.status, "error", None)
            raise RuntimeError(f"SQL {state}: {err}")
        if fetch and r.result and r.result.data_array:
            return r.result.data_array
        return []

    def create(self, filename: Optional[str]) -> Job:
        job = Job(id=str(uuid.uuid4()), filename=filename)
        self._exec(
            f"INSERT INTO {self.jobs}(id,status,filename,created_at,updated_at) "
            "VALUES(:id,:status,:filename,:created_at,:updated_at)",
            params={"id": job.id, "status": job.status.value, "filename": filename,
                    "created_at": job.created_at, "updated_at": job.updated_at},
        )
        self.append_audit(job.id, "RECEIVED", f"job created for {filename}")
        return job

    def get(self, job_id: str) -> Optional[Job]:
        rows = self._exec(
            "SELECT id,status,filename,created_at,updated_at,was_scan,source_path,tier_used,"
            f"result_json,error FROM {self.jobs} WHERE id=:id",
            params={"id": job_id}, fetch=True,
        )
        if not rows:
            return None
        r = rows[0]
        result = Invoice.model_validate_json(r[8]) if r[8] else None
        return Job(
            id=r[0], status=JobStatus(r[1]), filename=r[2], created_at=r[3], updated_at=r[4],
            was_scan=_as_bool(r[5]), source_path=r[6], tier_used=r[7], result=result, error=r[9],
        )

    def update(self, job_id: str, **fields) -> None:
        sets: dict[str, object] = {"updated_at": _now()}
        for key, value in fields.items():
            if key == "status" and isinstance(value, JobStatus):
                value = value.value
            elif key == "result" and isinstance(value, Invoice):
                key, value = "result_json", value.model_dump_json()
            sets[key] = value
        assignments = ",".join(f"{k}=:{k}" for k in sets)
        self._exec(
            f"UPDATE {self.jobs} SET {assignments} WHERE id=:_id",
            params={**sets, "_id": job_id},
        )

    def append_audit(self, job_id: str, stage: str, detail: str) -> None:
        self._exec(
            f"INSERT INTO {self.audit}(event_id,job_id,ts,stage,detail) "
            "VALUES(:event_id,:job_id,:ts,:stage,:detail)",
            params={"event_id": str(uuid.uuid4()), "job_id": job_id, "ts": _now(),
                    "stage": stage, "detail": detail},
        )

    def get_audit(self, job_id: str) -> list[dict]:
        rows = self._exec(
            f"SELECT ts,stage,detail FROM {self.audit} WHERE job_id=:id ORDER BY ts",
            params={"id": job_id}, fetch=True,
        )
        return [{"ts": r[0], "stage": r[1], "detail": r[2]} for r in rows]

    def store_document(self, job_id: str, filename: Optional[str], data: bytes) -> str:
        """Retain the raw PDF in the UC Volume under the job id; return its volume path."""
        name = filename or "document.pdf"
        path = f"{self.volume_root}/{job_id}/{name}"
        self._w.files.upload(path, io.BytesIO(data), overwrite=True)
        return path
