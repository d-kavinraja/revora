import asyncio
import uuid
from contextlib import asynccontextmanager
from unittest.mock import patch

from app.db.session import AsyncSessionLocal
from app.queue import operation_worker as ow
from app.queue.operation_worker import (
    claim_next_operation_job,
    run_operation_job,
    set_session_factory,
)


@asynccontextmanager
async def _test_session_cm(test_db):
    yield test_db


async def _noop_heartbeat(*args, **kwargs):
    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        return


async def run_operation_job_inline(client, test_db, job_id):
    def _factory():
        return _test_session_cm(test_db)

    set_session_factory(_factory)
    try:
        with patch.object(ow, "_heartbeat", _noop_heartbeat):
            claimed = await claim_next_operation_job(test_db)
            print("HELPER claimed", claimed.id if claimed else None, getattr(claimed,'worker_id',None) if claimed else None)
            await run_operation_job(uuid.UUID(str(job_id)))
            print("HELPER run done")
    finally:
        set_session_factory(AsyncSessionLocal)

    resp = client.get(f"/api/v1/operations/{job_id}")
    print("HELPER status", resp.status_code, resp.json().get("status"), resp.json().get("error_text"))
    assert resp.status_code == 200, resp.text
    return resp.json()


def job_items(job):
    return (job.get("result") or {}).get("items") or {}


def job_summary(job):
    return (job.get("result") or {}).get("summary") or {}
