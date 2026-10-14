import asyncio
import base64
import logging
import os
import re
import shutil
import subprocess
import tempfile

from git import Repo

from app.core.config import settings

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")

logger = logging.getLogger(__name__)


def _dir_size_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


class GitService:
    """Utility class for cloning and analyzing repositories."""

    @staticmethod
    async def clone_repository(
        clone_url: str, token: str, head_sha: str | None = None
    ) -> str:
        """
        Clones a repository securely into a temporary directory.
        Uses the provided installation token via a transient git header —
        the token NEVER appears in any URL, config, or log.
        """
        # Validate the requested commit first: GitPython passes head_sha to
        # `git checkout`, so a value starting with '-' would be parsed as a
        # flag (argument injection). Only accept hex SHAs.
        if head_sha is not None and not _SHA_RE.match(head_sha):
            raise ValueError("Invalid head_sha: must be a 7-40 char hex commit SHA")

        # Scheme guard: only http(s) remotes are cloned. The transient
        # header below is only meaningful over HTTP(S).
        scheme = (clone_url.split("://", 1)[0] if "://" in clone_url else "").lower()
        if scheme not in ("http", "https"):
            raise ValueError("Invalid clone URL: only http(s) remotes are allowed")

        timeout = max(10, int(settings.GIT_CLONE_TIMEOUT_S or 120))
        max_bytes = max(1, int(settings.GIT_CLONE_MAX_MB or 250)) * 1024 * 1024

        temp_dir = tempfile.mkdtemp(prefix="revora_repo_")

        def _clone():
            # Transient per-command header: git applies `-c` overrides only
            # to THIS process — nothing is written to .git/config, so there
            # is no persisted credential even if the clone crashes mid-way.
            cmd = ["git"]
            if token:
                credential = base64.b64encode(
                    f"x-access-token:{token}".encode("utf-8")
                ).decode("ascii")
                cmd += [
                    "-c",
                    f"http.extraHeader=Authorization: Basic {credential}",
                ]
            # `--` separates refs from paths; `--quiet` keeps token-adjacent
            # noise (URLs, progress lines) out of captured output.
            cmd += ["clone", "--quiet", "--", clone_url, temp_dir]
            proc = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=timeout,
                check=False,
            )
            if proc.returncode != 0:
                raise RuntimeError(
                    "Failed to clone repository. Please check the URL and your access token."
                )
            size = _dir_size_bytes(temp_dir)
            if size > max_bytes:
                raise ValueError(
                    f"Repository is too large "
                    f"({size // (1024 * 1024)} MB exceeds the "
                    f"{settings.GIT_CLONE_MAX_MB} MB limit)."
                )
            repo = Repo(temp_dir)
            if head_sha:
                repo.git.checkout("--", head_sha)

        try:
            await asyncio.to_thread(_clone)
        except Exception:
            # Never leave a half-cloned repo (possibly with credentials in
            # transient state) on disk: clean up before re-raising.
            try:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass
            raise

        return temp_dir

    @staticmethod
    async def cleanup_repository(repo_path: str):
        """Removes the temporary cloned repository."""

        def _cleanup():
            if os.path.exists(repo_path) and repo_path.startswith(
                tempfile.gettempdir()
            ):
                shutil.rmtree(repo_path, ignore_errors=True)

        await asyncio.to_thread(_cleanup)
