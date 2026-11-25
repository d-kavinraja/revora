import assert from 'node:assert/strict';
import test from 'node:test';

import {
  SpeechNdjsonParser,
  SpeechRequestError,
  formatSpeechError,
  insertTranscript,
  parseSpeechErrorResponse,
  pickRecorderMime,
  readSpeechStream,
} from './speech-core.ts';

test('insertTranscript adds a separator without altering the draft', () => {
  const result = insertTranscript('Hello', '  world  ', 100);
  assert.deepEqual(result, { ok: true, value: 'Hello world', caret: 11 });
});

test('insertTranscript preserves a deliberate trailing newline', () => {
  const result = insertTranscript('Hello\n', 'world', 100);
  assert.equal(result.ok, true);
  assert.equal(result.value, 'Hello\nworld');
});

test('insertTranscript collapses whitespace only inside the transcript', () => {
  const result = insertTranscript('Keep   draft', 'one\n\ntwo   three', 100);
  assert.equal(result.ok, true);
  assert.equal(result.value, 'Keep   draft one two three');
});

test('insertTranscript rejects an empty transcript and an overlong result', () => {
  assert.deepEqual(insertTranscript('draft', '   ', 100), { ok: false, reason: 'empty' });
  const over = insertTranscript('a'.repeat(95), 'bbbbbb', 100);
  assert.deepEqual(over, { ok: false, reason: 'too_long' });
});

test('insertTranscript keeps the exact character ceiling', () => {
  const exact = insertTranscript('a'.repeat(89), 'b'.repeat(10), 100);
  assert.equal(exact.ok, true);
  assert.equal(exact.value.length, 100);
  assert.equal(insertTranscript('a'.repeat(90), 'b'.repeat(10), 100).ok, false);
});

test('NDJSON parser handles split chunks, CRLF and a final line without newline', () => {
  const parser = new SpeechNdjsonParser();
  assert.deepEqual(parser.push('{"type":"que'), []);
  assert.deepEqual(parser.push('ued"}\r\n{"type":"pro'), [{ type: 'queued' }]);
  assert.deepEqual(parser.push('cessing"}\n'), [{ type: 'processing' }]);
  assert.deepEqual(parser.push('{"type":"result","text":" hello "}'), []);
  assert.deepEqual(parser.flush(), [{ type: 'result', text: 'hello' }]);
});

test('NDJSON parser accepts error events and bounds their message', () => {
  const parser = new SpeechNdjsonParser();
  const events = parser.push(
    JSON.stringify({ type: 'error', code: 'speech_timeout', message: 'x'.repeat(500) }) + '\n',
  );
  assert.equal(events.length, 1);
  assert.equal(events[0].type, 'error');
  assert.equal(events[0].code, 'speech_timeout');
  assert.equal(events[0].message.length, 300);
});

test('NDJSON parser rejects malformed and unknown events', () => {
  assert.throws(() => new SpeechNdjsonParser().push('not json\n'), SpeechRequestError);
  assert.throws(
    () => new SpeechNdjsonParser().push('{"type":"mystery"}\n'),
    SpeechRequestError,
  );
  assert.throws(
    () => new SpeechNdjsonParser().push('{"type":"result","text":""}\n'),
    SpeechRequestError,
  );
  assert.throws(
    () => new SpeechNdjsonParser().push('{"type":"result","text":"' + 'x'.repeat(20_001) + '"}\n'),
    SpeechRequestError,
  );
});

test('NDJSON parser rejects a line larger than its bound', () => {
  const parser = new SpeechNdjsonParser();
  assert.throws(() => parser.push('x'.repeat(64 * 1024 + 1)), SpeechRequestError);
});

test('recorder MIME choice prefers a supported container', () => {
  assert.equal(
    pickRecorderMime((mime) => mime === 'audio/webm'),
    'audio/webm',
  );
  assert.equal(
    pickRecorderMime((mime) => mime === 'audio/mp4'),
    'audio/mp4',
  );
  assert.equal(pickRecorderMime(() => false), null);
});

test('speech error copy is safe and maps known codes', () => {
  assert.match(formatSpeechError('speech_busy'), /busy/i);
  assert.match(formatSpeechError('permission_denied'), /Microphone access/i);
  assert.match(formatSpeechError('message_too_long'), /too long/i);
  assert.match(formatSpeechError('something_unexpected'), /Try again/i);
});

function responseFrom(chunks) {
  const encoder = new TextEncoder();
  return new Response(
    new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    }),
    { status: 200 },
  );
}

test('readSpeechStream delivers queued, processing and result events', async () => {
  const events = [];
  await readSpeechStream(
    responseFrom(['{"type":"que', 'ued"}\n{"type":"proc', 'essing"}\n{"type":"result","text":"hello"}\n']),
    (event) => events.push(event),
  );
  assert.deepEqual(events, [
    { type: 'queued' },
    { type: 'processing' },
    { type: 'result', text: 'hello' },
  ]);
});

test('readSpeechStream stops at a terminal event and ignores trailing lines', async () => {
  const events = [];
  await readSpeechStream(
    responseFrom(['{"type":"result","text":"one"}\n{"type":"result","text":"two"}\n']),
    (event) => events.push(event),
  );
  assert.deepEqual(events, [{ type: 'result', text: 'one' }]);
});

test('readSpeechStream reports an error event and a stream without a result', async () => {
  const events = [];
  await readSpeechStream(
    responseFrom(['{"type":"error","code":"speech_timeout","message":"slow"}\n']),
    (event) => events.push(event),
  );
  assert.equal(events[0].type, 'error');
  await assert.rejects(
    readSpeechStream(responseFrom(['{"type":"queued"}\n']), () => {}),
    (error) => error.code === 'speech_upstream_error',
  );
});

test('readSpeechStream honors an already-aborted signal', async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    readSpeechStream(responseFrom(['{"type":"queued"}\n']), () => {}, controller.signal),
    (error) => error.name === 'AbortError',
  );
});

test('parseSpeechErrorResponse prefers the backend code and status', async () => {
  const error = await parseSpeechErrorResponse(
    new Response(JSON.stringify({ detail: { code: 'speech_busy', message: 'Busy.' } }), {
      status: 429,
    }),
  );
  assert.equal(error.code, 'speech_busy');
  assert.equal(error.status, 429);
  assert.equal(error.message, 'Busy.');
  const unauthorized = await parseSpeechErrorResponse(new Response('no', { status: 401 }));
  assert.equal(unauthorized.code, 'unauthorized');
  assert.equal(unauthorized.status, 401);
});
test('readSpeechStream keeps a result before trailing unterminated garbage', async () => {
  const events = [];
  await readSpeechStream(
    responseFrom(['{"type":"result","text":"ok"}\nnot-json']),
    (event) => events.push(event),
  );
  assert.deepEqual(events, [{ type: 'result', text: 'ok' }]);
});
