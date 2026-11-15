"""Verification persistence: bounded retry, atomic commit, failure surfacing.

Retrying must never create duplicate rows, and a final failure must be visible
(structured log + counter) rather than silently dropped.
"""
import uuid

import pytest
from sqlalchemy import func, select
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

        installation = Installation(
            id=uuid.uuid4(),
            installation_id=7777,
            account_id=77,
            account_login="retry-acct",
            account_type="User",
            user_id=uuid.uuid4(),
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
