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


def _git_fetch_with_auth(
    repo_path: str, token: str, *refs: str, timeout: int = 120
) -> None:
    """Fetch refs from origin using a transient auth header.

    Credentials are passed via ``GIT_CONFIG_*`` environment variables so
    they never appear in process arguments (``ps``), Git config files, or
    error messages.  The env vars are scoped to this subprocess only.
    """
    env = os.environ.copy()
    if token:
        credential = base64.b64encode(
            f"x-access-token:{token}".encode("utf-8")
        ).decode("ascii")
        env["GIT_CONFIG_COUNT"] = "1"
        env["GIT_CONFIG_KEY_0"] = "http.extraHeader"
        env["GIT_CONFIG_VALUE_0"] = f"Authorization: Basic {credential}"
    cmd = ["git", "fetch", "origin", *refs]
    proc = subprocess.run(
        cmd,
        cwd=repo_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"git fetch failed (exit {proc.returncode}) for {refs}"
        )


class GitService:
    """Utility class for cloning and analyzing repositories."""

    @staticmethod
    async def clone_repository(
        clone_url: str,
        token: str,
        head_sha: str | None = None,
        pr_number: int | None = None,
    ) -> str:
        """
        Clones a repository securely into a temporary directory.
        Uses the provided installation token via a transient git header —
        the token NEVER appears in any URL, config, or log.

        When ``head_sha`` is provided, the commit is fetched from origin
        (PR refs are fetched for GitHub pull requests, including forks) and
        verified before checkout. ``pr_number`` enables fetching
        ``refs/pull/{n}/head``, which works for both same-repo and fork
        pull requests.
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
                # GitHub exposes pull request heads (same-repo and fork) at
                # refs/pull/{n}/head. Fetching it brings fork commits into the
                # local object store without relying on any branch ref.
                #
                # Authentication uses GIT_CONFIG_* environment variables
                # (transient, scoped to the subprocess) so the credential
                # never appears in process arguments, Git config, or logs.
                if pr_number is not None:
                    try:
                        _git_fetch_with_auth(
                            temp_dir, token, f"refs/pull/{pr_number}/head"
                        )
                    except Exception as fetch_error:
                        logger.warning(
                            "Failed to fetch refs/pull/%s/head: %s",
                            pr_number,
                            fetch_error,
                        )
                # Best-effort direct fetch of the exact commit (works when the
                # server allows fetching arbitrary reachable SHAs).
                try:
                    _git_fetch_with_auth(temp_dir, token, head_sha)
                except Exception as fetch_error:
                    logger.debug(
                        "Direct fetch of %s failed (will rely on PR ref or clone): %s",
                        head_sha,
                        fetch_error,
                    )

                # The commit must be present locally before we can check it
                # out; a force-pushed or fork-only SHA that was never fetched
                # is reported with a clear message instead of a confusing
                # pathspec error.
                try:
                    repo.git.cat_file("-e", f"{head_sha}^{{commit}}")
                except Exception as verify_error:
                    raise RuntimeError(
                        f"Commit {head_sha} not found in {clone_url}. "
                        "It may belong to a force-pushed or deleted branch."
                    ) from verify_error

                # Detach to the exact commit. NOTE: do not pass `--` here —
                # it would make git treat the SHA as a pathspec, not a ref.
                repo.git.checkout(head_sha)

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
