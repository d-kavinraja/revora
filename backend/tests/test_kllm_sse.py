"""Unit tests for the incremental kLLM SSE decoder.

No network access and no live inference.
"""

from __future__ import annotations

from app.ai.kllm_sse import SseDecoder, SseFrame, decode_frames


def test_decode_frames_handles_lf_and_crlf():
    frames, rest = decode_frames(
        'event: message\r\ndata: {"a":1}\r\n\r\n'
        'data: {"b":2}\n\n'
    )
    assert [f.data for f in frames] == ['{"a":1}', '{"b":2}']
    assert frames[0].event == "message"
    assert frames[1].event is None
    assert rest == ""


def test_decode_frames_keeps_partial_block_as_rest():
    frames, rest = decode_frames(
        'data: {"type":"delta","content":"Hel"}\n\n'
        'data: {"type":"delta","content":"lo"}'
    )
    assert len(frames) == 1
    assert frames[0].data == '{"type":"delta","content":"Hel"}'
    assert rest == 'data: {"type":"delta","content":"lo"}'


def test_decode_frames_ignores_empty_events_but_surfaces_comments():
    frames, rest = decode_frames(
        ": kllm: waiting (5s)\n\n"
        "event: ping\ndata:\n\n"
        'data: {"type":"delta","content":"x"}\n\n'
    )
    # Comment-only blocks are surfaced as non-content keepalive markers; the
    # empty `data:` event is ignored entirely.
    assert [f.keepalive for f in frames] == [True, False]
    assert frames[0].data == ""
    assert frames[1].data == '{"type":"delta","content":"x"}'
    assert rest == ""


def test_decode_frames_joins_multiple_data_lines_and_strips_one_space():
    frames, _ = decode_frames("data: one\ndata:  two\n\n")
    assert len(frames) == 1
    assert frames[0].data == "one\n two"


def test_decoder_accumulates_partial_chunks():
    decoder = SseDecoder()
    assert decoder.feed('data: {"type":"del') == []
    assert decoder.feed('ta","content":"hi"}\n\ndata: [DONE]\n\n') == [
        SseFrame(event=None, data='{"type":"delta","content":"hi"}'),
        SseFrame(event=None, data="[DONE]"),
    ]
    assert decoder.close() == []


def test_decoder_close_flushes_trailing_frame_without_blank_line():
    decoder = SseDecoder()
    assert decoder.feed('data: {"type":"done"}') == []
    flushed = decoder.close()
    assert len(flushed) == 1
    assert flushed[0].data == '{"type":"done"}'


def test_comment_keepalive_is_a_non_content_frame():
    frames, rest = decode_frames(": kllm: prefilling\n\n")
    assert rest == ""
    assert len(frames) == 1
    assert frames[0].keepalive is True
    assert frames[0].data == ""
    assert frames[0].event is None


def test_comment_beside_data_stays_a_regular_frame():
    frames, _ = decode_frames(': kllm: prefilling\ndata: {"a":1}\n\n')
    assert len(frames) == 1
    assert frames[0].keepalive is False
    assert frames[0].data == '{"a":1}'
