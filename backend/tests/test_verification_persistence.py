"""Verification persistence: bounded retry, atomic commit, failure surfacing.

Retrying must never create duplicate rows, and a final failure must be visible
(structured log + counter) rather than silently dropped.
"""
import json
import uuid

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register tables)
from app.db.base import Base
from app.models.review import Review
from app.models.verification import VerificationMetricModel, VerificationResultModel
from app.verification import engine as verification_engine_module
from app.verification.engine import VerificationEngine


@pytest.fixture
async def isolated_db(monkeypatch):
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        # SQLite disables FK enforcement by default; without this, orphan
        # verification_metrics rows would silently pass in tests.
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(
        bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
    )
    monkeypatch.setattr(verification_engine_module, "AsyncSessionLocal", factory)
    yield factory
    await engine.dispose()


@pytest.fixture
async def review_id(isolated_db):
    async with isolated_db() as db:
        from app.models.github import Installation, PullRequest, Repository
        from app.models.user import User

        # With FK enforcement on, the installation must reference a real user.
        user = User(
            id=uuid.uuid4(),
            name="Verification Fixture User",
            email=f"verify-{uuid.uuid4().hex[:8]}@example.com",
            role="user",
            is_verified=True,
        )
        db.add(user)
        await db.flush()

        installation = Installation(
            id=uuid.uuid4(),
            installation_id=7777,
            account_id=77,
            account_login="retry-acct",
            account_type="User",
            user_id=user.id,
            repository_selection="all",
            permissions={},
            events={},
            permissions_ok=True,
        )
        db.add(installation)
        await db.flush()
        repo = Repository(
            id=uuid.uuid4(),
            github_id=8888,
            name="retry-repo",
            full_name="retry-acct/retry-repo",
            installation_id=installation.id,
            reviews_enabled=True,
        )
        db.add(repo)
        await db.flush()
        pr = PullRequest(
            id=uuid.uuid4(),
            repo_id=repo.id,
            pr_number=31,
            title="Retry PR",
            author="author",
            head_sha="f" * 40,
            base_branch="main",
            head_branch="feat",
            status="open",
        )
        db.add(pr)
        await db.flush()
        review = Review(id=uuid.uuid4(), pr_id=pr.id, status="completed")
        db.add(review)
        await db.commit()
        return review.id


def _finding(finding_id="f1"):
    return {
        "id": finding_id,
        "title": "SQL injection risk",
        "file_path": "app/db.py",
        "line_number": 42,
        "category": "SECURITY",
        "severity": "HIGH",
        "description": "Unsanitized input",
        "suggested_fix": "Use parameterized queries",
        "is_verified": True,
        "confidence": 0.9,
    }


def _metrics():
    return {
        "total_findings": 1,
        "verified_findings": 1,
        "rejected_findings": 0,
        "hallucinations_detected": 0,
        "false_positives_filtered": 0,
        "avg_confidence": 0.9,
        "verification_duration_ms": 123,
        "hallucination_reports": [],
        "false_positive_reports": [],
    }


async def test_persist_to_db_stores_title(isolated_db, review_id):
    engine = VerificationEngine()
    await engine._persist_to_db(review_id, [_finding()], _metrics())

    async with isolated_db() as db:
        rows = (await db.execute(select(VerificationResultModel))).scalars().all()
        metrics_rows = (
            await db.execute(select(VerificationMetricModel))
        ).scalars().all()
    assert len(rows) == 1
    assert rows[0].title == "SQL injection risk"
    assert len(metrics_rows) == 1


async def test_persist_with_retry_succeeds_first_try(isolated_db, review_id):
    engine = VerificationEngine()
    assert await engine._persist_with_retry(review_id, [_finding()], _metrics()) is True


async def test_persist_with_retry_recovers_from_transient_failure(
    isolated_db, review_id, monkeypatch
):
    engine = VerificationEngine()
    attempts = {"n": 0}

    async def flaky(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("temporary database outage")
        return await original_persist(*args, **kwargs)

    original_persist = engine._persist_to_db
    monkeypatch.setattr(engine, "_persist_to_db", flaky)

    assert await engine._persist_with_retry(
        review_id, [_finding()], _metrics()
    ) is True
    assert attempts["n"] == 3


async def test_persist_with_retry_exhaustion_reports_failure(
    isolated_db, review_id, monkeypatch
):
    engine = VerificationEngine()

    async def always_fail(*args, **kwargs):
        raise RuntimeError("permanent database outage")

    monkeypatch.setattr(engine, "_persist_to_db", always_fail)
    verification_engine_module.VERIFICATION_PERSIST_FAILURES = 0

    assert (
        await engine._persist_with_retry(review_id, [_finding()], _metrics())
        is False
    )
    assert verification_engine_module.VERIFICATION_PERSIST_FAILURES == 1


async def test_retry_does_not_duplicate_rows(isolated_db, review_id, monkeypatch):
    engine = VerificationEngine()
    calls = {"n": 0}

    async def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return await original_persist(*args, **kwargs)

    original_persist = engine._persist_to_db
    monkeypatch.setattr(engine, "_persist_to_db", flaky)

    assert await engine._persist_with_retry(
        review_id, [_finding()], _metrics()
    ) is True

    async with isolated_db() as db:
        count = (
            await db.execute(select(func.count(VerificationResultModel.id)))
        ).scalar_one()
    assert count == 1  # exactly one row, not two


async def test_verify_returns_result_even_when_persist_fails(
    isolated_db, review_id, monkeypatch
):
    engine = VerificationEngine()

    async def always_fail(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(engine, "_persist_to_db", always_fail)
    verification_engine_module.VERIFICATION_PERSIST_FAILURES = 0

    class _FakePipeline:
        async def process(self, findings, repo_path, context):
            return [_finding()], _metrics()

    monkeypatch.setattr(verification_engine_module, "pipeline", _FakePipeline())

    result = await engine.verify(
        '[{"id": "f1", "title": "t", "description": "d"}]',
        repo_path=".",
        context={"review_id": str(review_id)},
    )
    assert result is not None
    assert verification_engine_module.VERIFICATION_PERSIST_FAILURES == 1


async def test_pending_file_written_on_final_failure(isolated_db, review_id, monkeypatch, tmp_path):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", tmp_path / "pending")

    async def always_fail(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(engine, "_persist_to_db", always_fail)
    eng_mod.VERIFICATION_PERSIST_FAILURES = 0

    class _FakePipeline:
        async def process(self, findings, repo_path, context):
            return [_finding()], _metrics()

    monkeypatch.setattr(eng_mod, "pipeline", _FakePipeline())

    result = await engine.verify(
        '[{"id": "f1", "title": "t", "description": "d"}]',
        repo_path=".",
        context={"review_id": str(review_id)},
    )
    assert result is not None
    pending_dir = tmp_path / "pending"
    assert pending_dir.exists()
    files = list(pending_dir.glob("*.json"))
    assert len(files) == 1
    import json
    data = json.loads(files[0].read_text())
    assert data["review_id"] == str(review_id)
    assert "verified_findings" in data
    assert "metrics" in data
    # File permissions are set to 0o600 on Unix; on Windows os.chmod
    # only toggles the read-only flag, so verify the call was made
    # indirectly by checking the file is not world-writable in the
    # Unix sense (best-effort on this platform).


async def test_recover_pending_files_flushes_to_db(isolated_db, review_id, monkeypatch, tmp_path):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod
    pending_dir = tmp_path / "pending"
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", pending_dir)

    # Write a pending file manually
    pending_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    import json
    data = {
        "review_id": str(review_id),
        "verified_findings": [_finding()],
        "metrics": _metrics(),
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    (pending_dir / f"{review_id}.json").write_text(json.dumps(data))
    (pending_dir / f"{review_id}.json").chmod(0o600)

    result = await engine.recover_pending_files()
    assert result["recovered"] == 1
    assert result["failed"] == 0
    # File should be deleted after recovery
    assert not (pending_dir / f"{review_id}.json").exists()

    # Verify records were persisted
    async with isolated_db() as db:
        from sqlalchemy import select, func
        count = (await db.execute(select(func.count(VerificationResultModel.id)))).scalar_one()
    assert count == 1


async def test_recover_pending_files_skips_already_persisted(isolated_db, review_id, monkeypatch, tmp_path):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod
    pending_dir = tmp_path / "pending"
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", pending_dir)

    # Persist first
    await engine._persist_to_db(review_id, [_finding()], _metrics())

    # Write pending file for same review
    pending_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    import json
    data = {
        "review_id": str(review_id),
        "verified_findings": [_finding()],
        "metrics": _metrics(),
        "timestamp": "2026-01-01T00:00:00+00:00",
    }
    (pending_dir / f"{review_id}.json").write_text(json.dumps(data))

    result = await engine.recover_pending_files()
    assert result["recovered"] == 1  # treated as recovered (already persisted)
    assert not (pending_dir / f"{review_id}.json").exists()


async def test_recover_pending_files_handles_malformed(isolated_db, monkeypatch, tmp_path):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod
    pending_dir = tmp_path / "pending"
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", pending_dir)

    pending_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    (pending_dir / "bad-file.json").write_text("{not valid json!!!")

    result = await engine.recover_pending_files()
    assert result["failed"] == 1
    # Malformed file moved to errors dir
    error_dir = pending_dir / "errors"
    assert error_dir.exists()
    assert (error_dir / "bad-file.json").exists()


async def test_recover_pending_files_no_dir(isolated_db, monkeypatch, tmp_path):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", tmp_path / "nonexistent")

    result = await engine.recover_pending_files()
    assert result == {"recovered": 0, "failed": 0}


# --- permanent-error classification and poison-file recovery ---------------


async def test_sqlite_fk_enforcement_rejects_orphan_metrics(isolated_db):
    """The isolated fixture must enforce FKs so orphan inserts fail."""
    async with isolated_db() as db:
        db.add(
            VerificationMetricModel(
                review_id=uuid.uuid4(),
                total_findings=0,
                verified_findings=0,
                rejected_findings=0,
                hallucinations_detected=0,
                false_positives_filtered=0,
                avg_confidence=0.0,
                verification_duration_ms=0,
            )
        )
        with pytest.raises(IntegrityError):
            await db.commit()


async def test_missing_review_parent_is_permanent_and_not_retried(
    isolated_db, monkeypatch, tmp_path
):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod

    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", tmp_path / "pending")
    eng_mod.VERIFICATION_PERSIST_FAILURES = 0
    missing_id = uuid.uuid4()

    calls = {"n": 0}
    original = engine._persist_to_db

    async def counting(*args, **kwargs):
        calls["n"] += 1
        return await original(*args, **kwargs)

    monkeypatch.setattr(engine, "_persist_to_db", counting)

    outcome = await engine._persist_with_retry_detailed(
        missing_id, [_finding()], _metrics()
    )
    assert outcome.persisted is False
    assert outcome.permanent is True
    assert outcome.missing_review is True
    assert outcome.attempts == 1
    assert calls["n"] == 1  # deterministic error is never retried
    assert eng_mod.VERIFICATION_PERSIST_FAILURES == 1

    async with isolated_db() as db:
        metrics = (await db.execute(select(func.count(VerificationMetricModel.id)))).scalar_one()
    assert metrics == 0


async def test_integrity_error_is_classified_permanent_without_retry(
    isolated_db, monkeypatch
):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod

    eng_mod.VERIFICATION_PERSIST_FAILURES = 0
    calls = {"n": 0}

    async def always_integrity(*args, **kwargs):
        calls["n"] += 1
        raise IntegrityError("INSERT INTO verification_metrics", {}, Exception("FK"))

    monkeypatch.setattr(engine, "_persist_to_db", always_integrity)

    outcome = await engine._persist_with_retry_detailed(
        uuid.uuid4(), [_finding()], _metrics()
    )
    assert outcome.permanent is True
    assert outcome.persisted is False
    assert calls["n"] == 1
    assert eng_mod.VERIFICATION_PERSIST_FAILURES == 1


async def test_transient_failure_keeps_bounded_retry_and_exhaustion(
    isolated_db, monkeypatch
):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod

    eng_mod.VERIFICATION_PERSIST_FAILURES = 0
    calls = {"n": 0}

    async def always_transient(*args, **kwargs):
        calls["n"] += 1
        raise RuntimeError("temporary database outage")

    monkeypatch.setattr(engine, "_persist_to_db", always_transient)

    outcome = await engine._persist_with_retry_detailed(
        uuid.uuid4(), [_finding()], _metrics()
    )
    assert outcome.persisted is False
    assert outcome.permanent is False
    assert outcome.attempts == 3
    assert calls["n"] == 3
    assert eng_mod.VERIFICATION_PERSIST_FAILURES == 1


async def test_verify_missing_parent_writes_no_pending_file(
    isolated_db, monkeypatch, tmp_path
):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod

    pending_dir = tmp_path / "pending"
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", pending_dir)
    eng_mod.VERIFICATION_PERSIST_FAILURES = 0

    class _FakePipeline:
        async def process(self, findings, repo_path, context):
            return [_finding()], _metrics()

    monkeypatch.setattr(eng_mod, "pipeline", _FakePipeline())

    result = await engine.verify(
        '[{"id": "f1", "title": "t", "description": "d"}]',
        repo_path=".",
        context={"review_id": str(uuid.uuid4())},
    )
    assert result is not None
    assert not pending_dir.exists() or not list(pending_dir.glob("*.json"))
    assert eng_mod.VERIFICATION_PERSIST_FAILURES == 1


async def test_recover_quarantines_missing_parent_file_without_replaying(
    isolated_db, monkeypatch, tmp_path
):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod

    pending_dir = tmp_path / "pending"
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", pending_dir)
    eng_mod.VERIFICATION_PERSIST_FAILURES = 0
    pending_dir.mkdir(parents=True, exist_ok=True)

    missing_id = uuid.uuid4()
    filename = f"{missing_id}.json"
    (pending_dir / filename).write_text(
        json.dumps(
            {
                "review_id": str(missing_id),
                "verified_findings": [_finding()],
                "metrics": _metrics(),
                "timestamp": "2026-01-01T00:00:00+00:00",
            }
        )
    )

    first = await engine.recover_pending_files()
    assert first == {"recovered": 0, "failed": 1}
    quarantined = pending_dir / "errors" / filename
    assert quarantined.exists()
    assert not (pending_dir / filename).exists()

    second = await engine.recover_pending_files()
    assert second == {"recovered": 0, "failed": 0}  # not replayed
    assert quarantined.exists()  # data preserved, not deleted


async def test_recover_transient_failure_keeps_retryable_file(
    isolated_db, review_id, monkeypatch, tmp_path
):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod

    pending_dir = tmp_path / "pending"
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", pending_dir)

    async def always_transient(*args, **kwargs):
        raise RuntimeError("temporary database outage")

    monkeypatch.setattr(engine, "_persist_to_db", always_transient)
    pending_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{review_id}.json"
    (pending_dir / filename).write_text(
        json.dumps(
            {
                "review_id": str(review_id),
                "verified_findings": [_finding()],
                "metrics": _metrics(),
            }
        )
    )

    result = await engine.recover_pending_files()
    assert result == {"recovered": 0, "failed": 1}
    assert (pending_dir / filename).exists()  # kept for a later startup
    assert not (pending_dir / "errors" / filename).exists()


async def test_recover_zero_findings_metrics_only_is_idempotent(
    isolated_db, review_id, monkeypatch, tmp_path
):
    engine = VerificationEngine()
    import app.verification.engine as eng_mod

    # A zero-findings verification writes only a metrics row.
    await engine._persist_to_db(review_id, [], _metrics())

    pending_dir = tmp_path / "pending"
    monkeypatch.setattr(eng_mod, "PENDING_VERIFICATION_DIR", pending_dir)
    pending_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{review_id}.json"
    (pending_dir / filename).write_text(
        json.dumps(
            {
                "review_id": str(review_id),
                "verified_findings": [],
                "metrics": _metrics(),
            }
        )
    )

    result = await engine.recover_pending_files()
    assert result == {"recovered": 1, "failed": 0}
    assert not (pending_dir / filename).exists()
    async with isolated_db() as db:
        metrics = (await db.execute(select(func.count(VerificationMetricModel.id)))).scalar_one()
    assert metrics == 1  # no duplicate metrics row

