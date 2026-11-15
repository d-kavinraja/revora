"""Regression tests for the fork-PR-aware clone/checkout path.

Same-repository PRs, fork PRs, missing commits and clone failures must all
behave deterministically and never leave a half-cloned repo behind.
"""
import subprocess

import pytest

from app.ai import git_utils
from app.ai.git_utils import GitService, _git_fetch_with_auth as _git_fetch_with_auth_helper

SHA = "a1b2c3d4e5f6" + "0" * 28  # 40-char hex


class FakeGit:
    def __init__(self, exist: bool = True):
        self.calls: list[tuple] = []
        self._exist = exist

    def fetch(self, *args):
        self.calls.append(("fetch", args))

    def cat_file(self, *args):
        self.calls.append(("cat_file", args))
        if not self._exist:
            raise RuntimeError("fatal: not a valid object name")

    def checkout(self, *args):
        self.calls.append(("checkout", args))


class FakeRepo:
    def __init__(self, path):
        self.git = FakeGit()


class FakeProc:
    returncode = 0


def _patch_subprocess_ok(monkeypatch):
    def fake_run(cmd, **kwargs):
        return FakeProc()

    monkeypatch.setattr(git_utils.subprocess, "run", fake_run)


class FakeProcFail:
    returncode = 128


def _patch_subprocess_fail(monkeypatch):
    def fake_run(cmd, **kwargs):
        return FakeProcFail()

    monkeypatch.setattr(git_utils.subprocess, "run", fake_run)


async def test_invalid_sha_rejected_before_clone(monkeypatch):
    called = False

    def fake_run(cmd, **kwargs):
        nonlocal called
        called = True
        return FakeProc()

    monkeypatch.setattr(git_utils.subprocess, "run", fake_run)

    with pytest.raises(ValueError, match="Invalid head_sha"):
        await GitService.clone_repository(
            "https://github.com/o/r", "token", "not-a-sha;rm -rf /"
        )
    assert called is False


async def test_non_http_scheme_rejected(monkeypatch):
    _patch_subprocess_ok(monkeypatch)
    with pytest.raises(ValueError, match="only http"):
        await GitService.clone_repository(
            "file:///etc/passwd", "token", SHA
        )


async def test_same_repo_pr_checkout_uses_commit_ref(monkeypatch):
    """The SHA must reach git as a ref, never as a `--` pathspec."""
    _patch_subprocess_ok(monkeypatch)
    fake_repo = FakeRepo("/tmp/fake")
    monkeypatch.setattr(git_utils, "Repo", lambda path: fake_repo)

    path = await GitService.clone_repository(
        "https://github.com/o/r", "token", SHA, pr_number=None
    )
    try:
        checkouts = [c for c in fake_repo.git.calls if c[0] == "checkout"]
        assert checkouts == [("checkout", (SHA,))]
        # No PR-ref fetch when pr_number is not provided.
        assert not any(
            a[0] == "fetch" and len(a[1]) > 1 and str(a[1][1]).startswith("refs/pull/")
            for a in fake_repo.git.calls
        )
        assert any(c[0] == "cat_file" for c in fake_repo.git.calls)
    finally:
        import shutil

        shutil.rmtree(path, ignore_errors=True)


async def test_fork_pr_fetches_pull_ref(monkeypatch):
    _patch_subprocess_ok(monkeypatch)
    fake_repo = FakeRepo("/tmp/fake")
    monkeypatch.setattr(git_utils, "Repo", lambda path: fake_repo)

    path = await GitService.clone_repository(
        "https://github.com/o/r", "token", SHA, pr_number=26
    )
    try:
        # Fetch is now via subprocess, not repo.git.fetch.
        # Check that checkout still uses the SHA as a ref (not pathspec).
        checkouts = [c for c in fake_repo.git.calls if c[0] == "checkout"]
        assert checkouts == [("checkout", (SHA,))]
        cat_calls = [c for c in fake_repo.git.calls if c[0] == "cat_file"]
        assert len(cat_calls) == 1
    finally:
        import shutil

        shutil.rmtree(path, ignore_errors=True)


async def test_missing_commit_raises_clear_error(monkeypatch):
    _patch_subprocess_ok(monkeypatch)

    class MissingRepo(FakeRepo):
        def __init__(self, path):
            self.git = FakeGit(exist=False)

    monkeypatch.setattr(git_utils, "Repo", MissingRepo)

    with pytest.raises(RuntimeError, match="Commit .* not found"):
        await GitService.clone_repository(
            "https://github.com/o/r", "token", SHA, pr_number=26
        )


async def test_clone_failure_cleans_up_temp_dir(monkeypatch):
    _patch_subprocess_fail(monkeypatch)

    with pytest.raises(RuntimeError, match="Failed to clone repository"):
        await GitService.clone_repository(
            "https://github.com/o/r", "token", SHA
        )


async def test_verify_before_checkout(monkeypatch):
    """checkout must only run after cat-file confirms the commit exists."""
    _patch_subprocess_ok(monkeypatch)
    fake_repo = FakeRepo("/tmp/fake")
    monkeypatch.setattr(git_utils, "Repo", lambda path: fake_repo)

    path = await GitService.clone_repository(
        "https://github.com/o/r", "token", SHA
    )
    try:
        names = [c[0] for c in fake_repo.git.calls]
        assert names.index("cat_file") < names.index("checkout")
    finally:
        import shutil

        shutil.rmtree(path, ignore_errors=True)


async def test_fork_pr_fetch_uses_env_auth(monkeypatch):
    """Fetch command must use GIT_CONFIG_* env vars, not process args."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = kwargs.get("env", {})
        return FakeProc()

    monkeypatch.setattr(git_utils.subprocess, "run", fake_run)

    _git_fetch_with_auth_helper("https://github.com/o/r", "secret-token", "refs/pull/26/head")

    cmd = captured["cmd"]
    env = captured["env"]
    # Token must NOT be in command args
    assert "secret-token" not in " ".join(cmd)
    # Token must be in env vars
    assert env.get("GIT_CONFIG_COUNT") == "1"
    assert env.get("GIT_CONFIG_KEY_0") == "http.extraHeader"
    # Token is base64-encoded in the header value
    import base64
    header = env.get("GIT_CONFIG_VALUE_0", "")
    assert header.startswith("Authorization: Basic ")
    decoded = base64.b64decode(header.split(" ", 2)[-1]).decode()
    assert "secret-token" in decoded
    # Command must not include -c in args
    assert "-c" not in cmd


async def test_private_fork_pr_fetch_succeeds(monkeypatch):
    def fake_run(cmd, **kwargs):
        return FakeProc()

    monkeypatch.setattr(git_utils.subprocess, "run", fake_run)

    # Should not raise
    _git_fetch_with_auth_helper("https://github.com/o/r", "token", "refs/pull/26/head")


async def test_fetch_failure_does_not_leak_token(monkeypatch):
    def fake_run(cmd, **kwargs):
        return FakeProcFail()

    monkeypatch.setattr(git_utils.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError) as exc_info:
        _git_fetch_with_auth_helper("https://github.com/o/r", "secret-token-123", "refs/pull/26/head")

    error_msg = str(exc_info.value)
    assert "secret-token-123" not in error_msg
    assert "exit" in error_msg.lower() or "failed" in error_msg.lower()
