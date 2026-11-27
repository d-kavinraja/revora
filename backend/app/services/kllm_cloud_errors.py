"""Error taxonomy for the kLLM Cloud provider.

Every error subclasses :class:`~app.services.kllm_service.KllmError` so the
existing managed-provider call sites (chat endpoint, review failover, review
worker) keep treating kLLM Cloud like any other server-owned provider, while
the cloud-specific ``code``/``reason_code`` still reach the client.

Messages are constant, safe strings: they never contain the relay URL, the
gateway key, upstream response bodies, model-loading state or account details.
"""

from __future__ import annotations

from app.services.kllm_service import KllmError


class KllmCloudError(KllmError):
    """Base kLLM Cloud error."""

    code = "kllm_cloud_error"
    status_code = 503


class KllmCloudDisabledError(KllmCloudError):
    code = "kllm_cloud_disabled"
    status_code = 503


class KllmCloudNotConfiguredError(KllmCloudError):
    code = "kllm_cloud_not_configured"
    status_code = 503


class KllmCloudInvalidModelError(KllmCloudError):
    code = "kllm_cloud_invalid_model"
    status_code = 400


class KllmCloudRequestError(KllmCloudError):
    code = "kllm_cloud_request_error"
    status_code = 400


class KllmCloudNotApprovedError(KllmCloudError):
    code = "kllm_cloud_not_approved"
    status_code = 404


class KllmCloudSurfaceDisabledError(KllmCloudError):
    code = "kllm_cloud_surface_disabled"
    status_code = 404


class KllmCloudUnavailableError(KllmCloudError):
    code = "kllm_cloud_unavailable"
    status_code = 503


class KllmCloudAuthError(KllmCloudError):
    code = "kllm_cloud_auth_error"
    status_code = 502


class KllmCloudProtocolError(KllmCloudError):
    code = "kllm_cloud_protocol_error"
    status_code = 502


class KllmCloudBusyError(KllmCloudError):
    code = "kllm_cloud_busy"
    status_code = 429


class KllmCloudTimeoutError(KllmCloudError):
    code = "kllm_cloud_timeout"
    status_code = 504
