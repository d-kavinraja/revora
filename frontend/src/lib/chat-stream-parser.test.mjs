import assert from 'node:assert/strict';
import test from 'node:test';

import { extractSseFrames, parseSseFrame } from './chat-stream-parser.ts';

test('extractSseFrames handles split and CRLF frames', () => {
  const first = extractSseFrames('data: {"type":"delta","content":"Hel"}\r\n\r\ndata: {"type":"del');
  assert.equal(first.frames.length, 1);
  assert.equal(first.rest, 'data: {"type":"del');
  const second = extractSseFrames(first.rest + 'ta","content":"lo"}\n\n');
  assert.equal(second.frames.length, 1);
  assert.deepEqual(parseSseFrame(second.frames[0]), { type: 'delta', content: 'lo' });
});

test('parseSseFrame parses done and error', () => {
  assert.deepEqual(parseSseFrame('data: {"type":"done","finish_reason":"stop"}'), {
    type: 'done',
    finish_reason: 'stop',
  });
  assert.deepEqual(parseSseFrame('data: {"type":"error","code":"x","message":"y"}'), {
    type: 'error',
    code: 'x',
    message: 'y',
  });
});

test('parseSseFrame preserves a length finish reason without coercion', () => {
  assert.deepEqual(parseSseFrame('data: {"type":"done","finish_reason":"length"}'), {
    type: 'done',
    finish_reason: 'length',
  });
});

test('each delta is emitted as it arrives, before the done event', () => {
  const frames = [
    'data: {"type":"delta","content":"Reverse "}',
    'data: {"type":"delta","content":"proxies "}',
    'data: {"type":"delta","content":"forward requests."}',
    'data: {"type":"done","finish_reason":"stop"}',
  ];
  const seen = [];
  for (const frame of frames) {
    const event = parseSseFrame(frame);
    if (event) seen.push(event);
  }
  const deltas = seen.filter((e) => e.type === 'delta');
  assert.equal(deltas.length, 3);
  assert.deepEqual(deltas.map((d) => d.content), [
    'Reverse ',
    'proxies ',
    'forward requests.',
  ]);
  assert.equal(seen.at(-1).type, 'done');
  assert.equal(
    deltas.map((d) => d.content).join(''),
    'Reverse proxies forward requests.',
  );
});

test('many streamed deltas are parsed without loss or duplication', () => {
  const raw = Array.from({ length: 200 }, (_, i) => {
    const frame = `data: {"type":"delta","content":"chunk-${i},"}`;
    return i % 7 === 0 ? `${frame}\r\n\r\n` : `${frame}\n\n`;
  }).join('');
  let buffer = raw;
  const parts = [];
  while (buffer) {
    const { frames, rest } = extractSseFrames(buffer);
    if (frames.length === 0) break;
    for (const frame of frames) {
      const event = parseSseFrame(frame);
      if (event?.type === 'delta') parts.push(event.content);
    }
    buffer = rest;
  }
  const expected = Array.from({ length: 200 }, (_, i) => `chunk-${i},`).join('');
  assert.equal(parts.join(''), expected);
});

test('parseSseFrame ignores malformed payloads', () => {
  assert.equal(parseSseFrame('data: {not json}'), null);
  assert.equal(parseSseFrame('event: ping'), null);
});

test('parseSseFrame parses presence-gated usage and timings', () => {
  assert.deepEqual(
    parseSseFrame(
      'data: {"type":"usage","prompt_tokens":12,"completion_tokens":4,"cache_read_input_tokens":3}',
    ),
    {
      type: 'usage',
      prompt_tokens: 12,
      completion_tokens: 4,
      cache_read_input_tokens: 3,
    },
  );
  assert.deepEqual(
    parseSseFrame(
      'data: {"type":"timings","gen_tps":45.5,"prompt_tps":1200,"cache_n":3}',
    ),
    { type: 'timings', gen_tps: 45.5, prompt_tps: 1200, cache_n: 3 },
  );
  // Only fields actually supplied are exposed.
  assert.deepEqual(parseSseFrame('data: {"type":"usage","prompt_tokens":1}'), {
    type: 'usage',
    prompt_tokens: 1,
  });
});

test('parseSseFrame parses prefill progress and model telemetry', () => {
  assert.deepEqual(
    parseSseFrame('data: {"type":"progress","cache":10,"processed":40,"total":80}'),
    { type: 'progress', cache: 10, processed: 40, total: 80 },
  );
  assert.deepEqual(parseSseFrame('data: {"type":"model","name":"qwen3.8-27b"}'), {
    type: 'model',
    name: 'qwen3.8-27b',
  });
  assert.deepEqual(parseSseFrame('data: {"type":"progress","total":"bad"}'), {
    type: 'progress',
  });
  assert.equal(parseSseFrame('data: {"type":"model","name":42}'), null);
});

test('unknown event types are ignored without breaking the stream', () => {
  assert.equal(parseSseFrame('data: {"type":"future_metric","value":1}'), null);
  assert.equal(parseSseFrame('data: {"type":"keepalive"}'), null);
});

test('parseSseFrame exposes only neutral status, never reasoning text', () => {
  assert.deepEqual(parseSseFrame('data: {"type":"status","status":"thinking"}'), {
    type: 'status',
    status: 'thinking',
  });
  assert.equal(
    parseSseFrame('data: {"type":"status","status":"thinking","reasoning_content":"secret"}')
      .reasoning_content,
    undefined,
  );
  assert.equal(parseSseFrame('data: {"reasoning_content":"raw chain"}'), null);
});
