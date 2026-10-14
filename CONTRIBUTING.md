# Contributing to Revora

Thanks for considering a contribution. This is a small, fast-moving codebase — a few conventions keep it that way.

## Workflow

1. Fork, branch from `main` (`feat/<topic>`, `fix/<topic>`, `chore/<topic>`).
2. Keep changes scoped; don't refactor unrelated code in the same PR.
3. Use [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `chore:`, `docs:`).

## Before pushing

- Backend: `pytest` green (runs on SQLite via `asyncio-mode=auto`; see `backend/pyproject.toml`).
- Frontend (from `frontend/`): `tsc --noEmit` clean, `eslint` clean on touched files, `next build` succeeds.
- Never commit secrets: `backend/.env`, `*.local` env files, keys, and tokens stay local. If you touch auth/session code, re-verify login → refresh → logout in the running app.

## What makes a good PR

- A problem statement linked to an issue, not just a diff.
- Tests for behavior changes (see `backend/tests/` patterns, e.g. `test_auth_me.py`).
- Docs updated alongside behavior changes (`README.md` claims must stay verifiable against code).

## What to avoid

- New dependencies without justification in the PR description.
- Changes to deployment files (`Dockerfile`, `docker-compose.*`) without noting the target environment.
- Pushing to someone else's feature branch; open a PR instead.
