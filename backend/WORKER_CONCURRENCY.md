# Revora — Review worker concurrency (local)

Revora can run multiple PR reviews in parallel. The execution model is
**PostgreSQL-backed job queue + a dedicated or embedded review worker**, not a
brokered task queue (no Celery/RQ/Redis queues).

## Architecture

```
FastAPI backend (uvicorn, 1 worker)
  ├─ enqueues review jobs              → review_jobs table (queued)
  ├─ maintenance gate, Admin API, etc.
  └─ may execute reviews in-process    (REVIEW_WORKER_ENABLED=true; used by run.bat)

Dedicated worker service (optional, no ports)
  └─ run_worker() claims jobs from PostgreSQL
     ├─ claim: SELECT ... FOR UPDATE SKIP LOCKED
     ├─ fairness: fewer running jobs first, then least-recently-completed repo
     ├─ concurrency: REVIEW_WORKER_CONCURRENCY jobs per process (default 5, max 5)
     └─ same repo can fill all 5 slots — no per-repo serialization
```

`run.bat` uses the embedded worker path (`--reload`) with
`REVIEW_WORKER_CONCURRENCY=5`. Docker Compose uses the optional `worker`
service and sets the backend `REVIEW_WORKER_ENABLED=false` so exactly one
review worker is active.

## Settings (in `app/core/config.py`)

| Variable | Default | Range | Purpose |
|---|---|---|---|
| `REVIEW_WORKER_ENABLED` | `true` | bool | Start the embedded review worker in FastAPI lifespan. Set `false` when using a dedicated `worker` service. |
| `REVIEW_WORKER_CONCURRENCY` | `5` | 1–5 | Max simultaneous jobs per process. `run.bat` sets it to `5` explicitly. |
| `REVIEW_WORKER_POLL_INTERVAL_SECONDS` | `2.0` | ≥ 0.1 | Queue polling interval. |
| `REVIEW_WORKER_SHUTDOWN_TIMEOUT_SECONDS` | `300` | ≥ 10 | Graceful shutdown window for active reviews. |
| `PROVIDER_CONCURRENCY_LIMIT` | `3` | 1–5 | Max concurrent LLM calls per provider. |

`REVIEW_WORKER_CONCURRENCY` is validated (`ge=1`, `le=5`). The localhost default
is now `5`; `run.bat` also sets `REVIEW_WORKER_CONCURRENCY=5` for clarity.

## Database pools

A single embedded worker holds at most 5 review slots simultaneously. Each
review opens short-lived transactional sessions for claims, execution
transitions and status writes; none of those sessions are held across provider
HTTP calls.

- Backend/API + embedded worker: `DATABASE_POOL_SIZE=10`, `DATABASE_MAX_OVERFLOW=5` → 15 max.
- Dedicated worker: same default/env model.
- PostgreSQL default `max_connections=100`; with a few admin/psql layers this is still well below 100.

## Claiming

- Claims are atomic: `SELECT ... FOR UPDATE SKIP LOCKED` (Postgres).
- Hyphenated repository IDs never receive a special restriction; the same repo may use all 5 slots.
- Fairness: repositories with fewer running jobs are preferred first, then least-recently-completed, then oldest queued job.
- FIFO ordering within a repository remains stable for jobs queued while slots are full.
- Two processes claim distinct jobs; each process's 5 slots are additive.

## Retries and recovery

- Stale `running` jobs (no heartbeat update for `heartbeat_timeout_seconds`)
  are re-queued on startup / recovery passes (max 3 attempts).
- Stale `queued` jobs older than `queue_timeout_minutes` are marked failed by
  the recovery pass.
- Cancellation is by status; the worker's per-job watcher (5 s) aborts a
  cancelled task. On graceful shutdown, in-flight tasks are cancelled and
  recorded as cancelled; anything left is recovered on the next start.

## Running locally without Docker

```powershell
cd .
run.bat
```

`run.bat` starts the API on port 8000 and the frontend on port 3000. The API
embeds the review worker and sets `REVIEW_WORKER_CONCURRENCY=5`.

You do not need to edit `backend/.env`. If you want to override the default,
set `REVIEW_WORKER_CONCURRENCY=5` for the backend process; unset it to use the
localhost default.

## Verifying five concurrent reviews

```powershell
cd backend
python -m pytest tests/test_worker_concurrency.py -q
```

`test_five_jobs_same_repo_run_in_parallel` asserts `max_active == 5`, and
`test_five_repos_run_five_in_parallel` does the same for 5 different repos.
Providers are mocked; no real API calls are made.

## Limitations

- Fairness is round-robin by repository running count and completion time; there is no per-user quota.
- The operation (non-review) worker remains at its own concurrency (`OPERATION_WORKER_CONCURRENCY`, default 1) and is intentionally unchanged.
- SSE still DB-polling; see `get_current_user_for_stream`.
- The `worker` compose service is optional for local Docker `run.bat` and is the production-style separation path.
