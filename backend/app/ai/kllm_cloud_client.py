"""Direct HTTP client for the kLLM Cloud relay.

The relay speaks the OpenAI wire protocol. Revora uses exactly three
endpoints, all server-side:

* ``GET  /v1/models``           - free catalogue + gateway liveness.
* ``GET  /health``              - backend-warm probe. The relay proxies it to a
  model backend, so a non-200 means "no backend is warm", never "the provider
  is down".
* ``POST /v1/chat/completions`` - Chat and Review inference.

Nothing else is reachable: no model-load/unload/warm-up call, no management
surface, no ``/admin`` or ``/__relay`` request, no analytics call. Redirects
are never followed, and neither the gateway key nor the relay origin can leak
into an error message, a log line or a response body.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.ai.kllm_client import ContentDelta, StreamMeta
from app.ai.kllm_sse import SseDecoder, SseFrame
from app.core.config import settings
from app.services.kllm_cloud_errors import (
    KllmCloudAuthError,
    KllmCloudBusyError,
    KllmCloudError,
    KllmCloudNotConfiguredError,
    KllmCloudProtocolError,
    KllmCloudRequestError,
    KllmCloudTimeoutError,
    KllmCloudUnavailableError,
)

logger = logging.getLogger(__name__)

#: The complete allowlist of relay paths Revora may request.
ALLOWED_PATHS = frozenset({"/v1/models", "/v1/chat/completions", "/health"})

#: Hostname suffixes that only make sense for an on-host relay.
_LOCAL_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home")

#: The catalogue probe never needs to wait as long as an inference read.
CATALOG_TIMEOUT_CAP_S = 30.0

_semaphores: dict[int, asyncio.Semaphore] = {}


def _dev_insecure_allowed() -> bool:
    """Plain-HTTP / private-address relays are a local-testing exception."""
    return bool(settings.KLLM_CLOUD_ALLOW_HTTP) and settings.APP_ENV.lower() in (
        "development",
        "testing",
    )


def _parse_ip(host: str):
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def validate_relay_url(raw: str | None = None) -> str:
    """Validate the configured relay origin and return it without a trailing /.

    Remote configuration is never trusted to point inside a network:

    * ``https`` only, unless ``KLLM_CLOUD_ALLOW_HTTP`` is set for local testing.
    * no credentials in the URL, no query, no fragment, no path.
    * loopback / private / link-local / reserved / multicast / unspecified
      addresses and ``.local``-style hostnames are refused, except for the
      explicit development exception above.
    """
    value = (settings.KLLM_CLOUD_BASE_URL if raw is None else raw) or ""
    value = value.strip()
    if not value:
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not configured on this server.",
            reason_code="not_configured",
            definitive=True,
        )
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not configured on this server.",
            reason_code="invalid_base_url",
            definitive=True,
        ) from None
    if parsed.scheme not in ("http", "https"):
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not configured on this server.",
            reason_code="invalid_base_url",
            definitive=True,
        )
    if parsed.username or parsed.password:
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not configured on this server.",
            reason_code="credentials_in_url",
            definitive=True,
        )
    if parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not configured on this server.",
            reason_code="invalid_base_url",
            definitive=True,
        )
    host = (parsed.hostname or "").strip().lower()
    # A fully-qualified name may carry a trailing root dot (``localhost.``,
    # ``127.0.0.1.``). It denotes the same host, so normalize it before every
    # check instead of letting it slip past the loopback/private guards.
    host = host.rstrip(".")
    if not host:
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not configured on this server.",
            reason_code="invalid_base_url",
            definitive=True,
        )
    insecure = parsed.scheme == "http"
    dev = _dev_insecure_allowed()
    if insecure and not dev:
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not configured on this server.",
            reason_code="insecure_transport",
            definitive=True,
        )
    address = _parse_ip(host)
    local_host = address is not None and (
        address.is_loopback
        or address.is_private
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )
    if address is None and (
        host == "localhost"
        # A single-label name (no dot) is a LAN/intranet name, never a public
        # relay origin; metadata-style aliases resolve to link-local space.
        or "." not in host
        or host.endswith(_LOCAL_HOST_SUFFIXES)
    ):
        local_host = True
    if local_host and not dev:
        raise KllmCloudNotConfiguredError(
            "kLLM Cloud is not configured on this server.",
            reason_code="private_destination",
            definitive=True,
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _get_semaphore(limit: int) -> asyncio.Semaphore:
    semaphore = _semaphores.get(limit)
    if semaphore is None:
        semaphore = asyncio.Semaphore(limit)
        _semaphores[limit] = semaphore
    return semaphore


def reset_runtime_state() -> None:
    """Drop cached semaphores (tests, and a changed concurrency limit)."""
    _semaphores.clear()


@dataclass(frozen=True)
class CloudCompletion:
    content: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None = None


def _text_from_content(value: Any) -> str:
    """Flatten an OpenAI ``content`` value (string or typed parts)."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return ""


def _safe_finish_reason(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()[:40]
    return None


class KllmCloudClient:
    """Single-shot completions, streaming, catalogue and health probes."""

    def endpoint(self, path: str) -> str:
        if path not in ALLOWED_PATHS:
            raise ValueError(f"Path not allowed for kLLM Cloud: {path}")
        return f"{validate_relay_url()}{path}"

    def is_configured(self) -> bool:
        try:
            validate_relay_url()
        except KllmCloudError:
            return False
        return True

    def credential_present(self) -> bool:
        return bool((settings.KLLM_CLOUD_API_KEY or "").strip())

    def _headers(self, *, stream: bool) -> dict[str, str]:
        headers = {
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
        }
        key = (settings.KLLM_CLOUD_API_KEY or "").strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _client(self, *, read_timeout: float) -> httpx.AsyncClient:
        timeout = httpx.Timeout(
            connect=settings.KLLM_CLOUD_CONNECT_TIMEOUT_S,
            read=max(read_timeout, settings.KLLM_CLOUD_CONNECT_TIMEOUT_S),
            write=120.0,
            pool=settings.KLLM_CLOUD_CONNECT_TIMEOUT_S,
        )
        return httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
        )

    @asynccontextmanager
    async def permit(self):
        """Bound concurrent relay requests; excessive queueing fails fast."""
        semaphore = _get_semaphore(settings.KLLM_CLOUD_CONCURRENCY_LIMIT)
        wait_for = settings.KLLM_CLOUD_QUEUE_TIMEOUT_S
        try:
            if wait_for and wait_for > 0:
                await asyncio.wait_for(semaphore.acquire(), timeout=wait_for)
            else:
                await semaphore.acquire()
        except TimeoutError:
            raise KllmCloudBusyError(
                "kLLM Cloud is at capacity. Please try again in a moment.",
                reason_code="concurrency_limit",
            ) from None
        try:
            yield
        finally:
            semaphore.release()

    def _status_error(self, status: int) -> KllmCloudError:
        if status in (401, 403):
            return KllmCloudAuthError(
                "kLLM Cloud rejected the server credentials.",
                reason_code="auth_rejected",
                definitive=True,
            )
        if status == 429:
            return KllmCloudBusyError(
                "kLLM Cloud is at capacity. Please try again in a moment.",
                reason_code="relay_busy",
            )
        if status == 404:
            return KllmCloudUnavailableError(
                "This model is not available in kLLM Cloud.",
                reason_code="model_not_found",
                definitive=True,
            )
        if 400 <= status < 500:
            return KllmCloudRequestError(
                "kLLM Cloud rejected this request.",
                reason_code="request_rejected",
                definitive=True,
            )
        return KllmCloudUnavailableError(
            "kLLM Cloud is temporarily unavailable. Please try again shortly.",
            reason_code="relay_unavailable",
        )

    def _transport_error(self, exc: Exception) -> KllmCloudError:
        if isinstance(exc, httpx.TimeoutException):
            return KllmCloudTimeoutError(
                "kLLM Cloud timed out while serving this request.",
                reason_code="timeout",
            )
        return KllmCloudUnavailableError(
            "kLLM Cloud could not be reached. Please try again shortly.",
            reason_code="relay_unreachable",
        )

    async def fetch_catalog(self) -> dict[str, Any]:
        """``GET /v1/models`` - free, answered by the gateway without a backend."""
        read = min(settings.KLLM_CLOUD_TIMEOUT, CATALOG_TIMEOUT_CAP_S)
        try:
            async with self._client(read_timeout=read) as client:
                response = await client.get(
                    self.endpoint("/v1/models"), headers=self._headers(stream=False)
                )
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from None
        if response.status_code >= 300:
            raise self._status_error(response.status_code)
        try:
            payload = response.json()
        except ValueError:
            raise KllmCloudProtocolError(
                "kLLM Cloud returned an unexpected catalogue response.",
                reason_code="invalid_catalog",
            ) from None
        if not isinstance(payload, dict):
            raise KllmCloudProtocolError(
                "kLLM Cloud returned an unexpected catalogue response.",
                reason_code="invalid_catalog",
            )
        return payload

    async def fetch_health(self) -> int:
        """``GET /health`` - status 200 means a model backend is warm."""
        read = min(settings.KLLM_CLOUD_TIMEOUT, CATALOG_TIMEOUT_CAP_S)
        try:
            async with self._client(read_timeout=read) as client:
                response = await client.get(
                    self.endpoint("/health"), headers=self._headers(stream=False)
                )
        except httpx.HTTPError as exc:
            raise self._transport_error(exc) from None
        return response.status_code

    def _payload(
        self,
        model: str,
        messages: list[Any],
        *,
        stream: bool,
        max_tokens: int | None,
        temperature: float | None,
    ) -> dict[str, Any]:
        # Only the documented OpenAI subset travels upstream: no stream_options,
        # no telemetry hints, no vendor extensions.
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": stream,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max(1, int(max_tokens))
        if temperature is not None:
            payload["temperature"] = float(temperature)
        return payload

    async def complete(
        self,
        model: str,
        messages: list[Any],
        *,
        max_tokens: int | None = 1024,
        temperature: float | None = None,
        timeout: float | None = None,
    ) -> CloudCompletion:
        payload = self._payload(
            model,
            messages,
            stream=False,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        read = timeout or settings.KLLM_CLOUD_TIMEOUT
        async with self.permit():
            try:
                async with self._client(read_timeout=read) as client:
                    response = await client.post(
                        self.endpoint("/v1/chat/completions"),
                        json=payload,
                        headers=self._headers(stream=False),
                    )
            except httpx.HTTPError as exc:
                raise self._transport_error(exc) from None
        if response.status_code >= 300:
            raise self._status_error(response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise KllmCloudProtocolError(
                "kLLM Cloud returned an unexpected response.",
                reason_code="invalid_response",
            ) from None
        if not isinstance(data, dict):
            raise KllmCloudProtocolError(
                "kLLM Cloud returned an unexpected response.",
                reason_code="invalid_response",
            )
        return self._parse_completion(model, data)

    def _parse_completion(
        self, model: str, data: dict[str, Any]
    ) -> CloudCompletion:
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise KllmCloudProtocolError(
                "kLLM Cloud returned an empty response.",
                reason_code="empty_response",
            )
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message") if isinstance(first, dict) else None
        content = _text_from_content(
            (message or {}).get("content") if isinstance(message, dict) else ""
        )
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        logger.info("kllm_cloud_completion model=%s chars=%s", model, len(content))
        return CloudCompletion(
            content=content,
            prompt_tokens=prompt_tokens if isinstance(prompt_tokens, int) else 0,
            completion_tokens=(
                completion_tokens if isinstance(completion_tokens, int) else 0
            ),
            finish_reason=_safe_finish_reason(first.get("finish_reason")),
        )

    async def stream(
        self,
        model: str,
        messages: list[Any],
        *,
        max_tokens: int | None = 1024,
        temperature: float | None = None,
    ) -> AsyncIterator[ContentDelta | StreamMeta]:
        payload = self._payload(
            model,
            messages,
            stream=True,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        async with self.permit():
            succeeded = False
            terminal_seen = False
            model_specific_unavailable = False
            try:
                async with self._client(
                    read_timeout=settings.KLLM_CLOUD_TIMEOUT
                ) as client:
                    async with client.stream(
                        "POST",
                        self.endpoint("/v1/chat/completions"),
                        json=payload,
                        headers=self._headers(stream=True),
                    ) as response:
                        if response.status_code >= 300:
                            await response.aread()
                            err = self._status_error(response.status_code)
                            if isinstance(err, KllmCloudUnavailableError) and getattr(
                                err, "reason_code", None
                            ) in ("model_not_found", "model_removed"):
                                model_specific_unavailable = True
                            raise err
                        decoder = SseDecoder()
                        async for chunk in response.aiter_text():
                            for frame in decoder.feed(chunk):
                                for item in self._frame_items(frame):
                                    if isinstance(item, StreamMeta) and item.kind in ("end", "done"):
                                        terminal_seen = True
                                    yield item
                        for frame in decoder.close():
                            for item in self._frame_items(frame):
                                if isinstance(item, StreamMeta) and item.kind in ("end", "done"):
                                    terminal_seen = True
                                yield item
                # Reaching here means the stream completed without an exception.
                # Only a stream that signalled a terminal marker counts as a
                # successful response; a bare EOF is "incomplete", not success.
                succeeded = terminal_seen
            except httpx.HTTPError as exc:
                mapped = self._transport_error(exc)
                raise mapped from None
            except KllmCloudError as exc:
                if getattr(exc, "reason_code", None) in (
                    "model_not_found",
                    "model_removed",
                ):
                    model_specific_unavailable = True
                raise
            finally:
                try:
                    from app.services import kllm_cloud_service

                    kllm_cloud_service.record_runtime_outcome(
                        model,
                        succeeded=succeeded,
                        model_specific_unavailable=model_specific_unavailable,
                    )
                except Exception:
                    pass

    def _frame_items(self, frame: SseFrame) -> list[ContentDelta | StreamMeta]:
        if frame.keepalive:
            return [StreamMeta("keepalive")]
        data = frame.data.strip()
        if not data:
            return []
        if data == "[DONE]":
            return [StreamMeta("end")]
        try:
            payload = json.loads(data)
        except ValueError:
            logger.warning("kllm_cloud_stream_bad_frame")
            return []
        if not isinstance(payload, dict):
            return []
        if payload.get("error"):
            raise KllmCloudUnavailableError(
                "kLLM Cloud could not answer this request. Please try again.",
                reason_code="upstream_error",
            )
        items: list[ContentDelta | StreamMeta] = []
        usage = payload.get("usage")
        if isinstance(usage, dict) and (
            isinstance(usage.get("prompt_tokens"), int)
            or isinstance(usage.get("completion_tokens"), int)
        ):
            items.append(
                StreamMeta(
                    "usage",
                    {
                        "prompt_tokens": usage.get("prompt_tokens") or 0,
                        "completion_tokens": usage.get("completion_tokens") or 0,
                    },
                )
            )
        choices = payload.get("choices")
        if isinstance(choices, list):
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    text = _text_from_content(delta.get("content"))
                    if text:
                        items.append(ContentDelta(text))
                    # Presence only: emit thinking status during reasoning phase
                    if delta.get("reasoning_content"):
                        items.append(StreamMeta("status", {"status": "thinking"}))
                reason = _safe_finish_reason(choice.get("finish_reason"))
                if reason:
                    items.append(StreamMeta("done", {"finish_reason": reason}))
        return items


kllm_cloud_client = KllmCloudClient()
