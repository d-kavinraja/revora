"""Incremental SSE decoding for the kLLM relay stream.

The relay forwards the upstream llama-server stream essentially verbatim, so a
single HTTP chunk can contain a partial frame, several frames, SSE comments
(``: kllm: waiting ...`` keep-alives), or an empty event. This module keeps the
framing concerns separate from the chat-client logic so they can be tested
independently.

No data is fabricated here: empty frames are ignored and comment-only frames
are surfaced as ``keepalive`` markers (never as content) so consumers can tell
a live prefill from a genuine stall.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SseFrame:
    """One decoded SSE event with an optional event name.

    ``keepalive`` marks a comment-only block (e.g. ``: kllm: prefilling``). It
    carries no data and must never be interpreted as model content.
    """

    event: str | None
    data: str
    keepalive: bool = False


def _parse_block(block: str) -> SseFrame | None:
    """Turn one blank-line-delimited block into a frame, or ``None`` if empty."""
    event: str | None = None
    data_lines: list[str] = []
    saw_comment = False

    for line in block.split("\n"):
        if not line:
            continue
        if line.startswith(":"):
            # SSE comments carry no data, but a relay prefill keepalive proves
            # the upstream is alive, so surface it as a non-content marker.
            saw_comment = True
            continue
        field, sep, value = line.partition(":")
        if not sep:
            continue
        if field == "event":
            event = value.strip()
        elif field == "data":
            # SSE removes a single leading space from data values.
            data_lines.append(value.removeprefix(" "))
        # ``id``, ``retry`` and unknown fields are intentionally ignored.

    if not data_lines:
        if saw_comment:
            return SseFrame(event=None, data="", keepalive=True)
        return None
    data = "\n".join(data_lines)
    if not data.strip():
        return None
    return SseFrame(event=event, data=data)


def decode_frames(text: str) -> tuple[list[SseFrame], str]:
    """Decode all complete frames in ``text`` and return ``(frames, rest)``.

    ``rest`` is the trailing partial block that must be kept for the next call.
    Both LF and CRLF (and bare CR) delimiters are accepted.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    parts = normalized.split("\n\n")
    rest = parts.pop() if parts else ""
    frames: list[SseFrame] = []
    for part in parts:
        frame = _parse_block(part)
        if frame is not None:
            frames.append(frame)
    return frames, rest


class SseDecoder:
    """Stateful wrapper around :func:`decode_frames` for streaming readers."""

    def __init__(self) -> None:
        self._buffer = ""

    def feed(self, chunk: str) -> list[SseFrame]:
        """Add a decoded text chunk and return any newly completed frames."""
        self._buffer += chunk
        frames, self._buffer = decode_frames(self._buffer)
        return frames

    def close(self) -> list[SseFrame]:
        """Flush a trailing frame that lacked its terminating blank line."""
        if not self._buffer.strip():
            self._buffer = ""
            return []
        frames, rest = decode_frames(self._buffer + "\n\n")
        self._buffer = rest
        return frames
