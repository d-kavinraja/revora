# Security Policy

## Reporting a vulnerability

**Do not open a public issue** for anything security-sensitive.

Use GitHub's **private vulnerability reporting** on this repository
(Security tab → Report a vulnerability). Include:

- What you found and where (file, endpoint, commit).
- Steps to reproduce, and what an attacker gains.
- Whether you believe it is already being exploited.

You will get an initial response as fast as maintenance bandwidth allows;
this is a solo/small-team project, so please allow a few days. Verified
reports are fixed on a feature branch first, then merged — reporters are
credited unless they ask not to be.

## Scope notes

- In scope: the FastAPI backend, the Next.js frontend/BFF, auth and session
  handling, webhook signature verification, stored provider keys.
- The hosted MouthMap inference Space and any LLM provider APIs are third
  parties — report their issues to their vendors, and report integration
  flaws here.
- Please do not exfiltrate other users' data, spam PR webhooks at a live
  deployment, or run scanners that degrade the service while testing.
