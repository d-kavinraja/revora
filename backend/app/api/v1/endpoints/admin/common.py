"""Shared helpers for the admin read endpoints."""

from fastapi import HTTPException, status

from app.services.admin_stats import InvalidQuery


def http_400(exc: InvalidQuery) -> HTTPException:
    """Map an invalid admin query parameter to a 400 (plan §18)."""
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
    )
