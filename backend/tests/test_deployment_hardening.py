"""N8/N9 — production docs are disabled; migration refuses a dead database.

Both run in subprocesses so the app module and alembic environment are
imported fresh with explicit environment variables.
"""
import os
import subprocess
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _run(args: list[str], env_updates: dict[str, str], timeout: int = 120):
    env = os.environ.copy()
    env.update(env_updates)
    return subprocess.run(
        [sys.executable, *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def test_n8_production_disables_interactive_docs():
    code = (
        "from app.main import app\n"
        "from fastapi.testclient import TestClient\n"
        "client = TestClient(app)\n"
        "root = client.get('/').json()\n"
        "docs = client.get('/docs').status_code\n"
        "redoc = client.get('/redoc').status_code\n"
        "openapi = client.get('/openapi.json').status_code\n"
        "print('docs', app.docs_url, app.redoc_url, app.openapi_url)\n"
        "print('root', root)\n"
        "print('codes', docs, redoc, openapi)\n"
    )
    result = _run(["-c", code], {"APP_ENV": "production"})
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "docs None None None" in output
    assert "codes 404 404 404" in output
    assert "'message': 'Revora API'" in output
    assert "Visit /docs" not in output


def test_n8_development_keeps_docs_available():
    code = (
        "from app.main import app\n"
        "print('docs', app.docs_url, app.redoc_url, app.openapi_url)\n"
    )
    result = _run(["-c", code], {"APP_ENV": "development"})
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
    assert "docs /docs /redoc /openapi.json" in output


def test_n9_unreachable_configured_database_aborts_migration():
    result = _run(
        [
            "-m",
            "alembic",
            "upgrade",
            "head",
            "--sql",
        ],
        {
            "DATABASE_URL": "postgresql://test:test@127.0.0.1:9/testdb",
            "APP_ENV": "development",
        },
        timeout=180,
    )
    output = result.stdout + result.stderr

    assert result.returncode != 0, output
    assert "unreachable" in output
    assert "revora.db" not in output or "refusing to fall back" in output


def test_n9_sqlite_url_is_accepted(tmp_path):
    db_file = tmp_path / "n9_sqlite_check.db"
    result = _run(
        ["-m", "alembic", "stamp", "head"],
        {
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_file.as_posix()}",
            "APP_ENV": "development",
        },
        timeout=180,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 0, output
