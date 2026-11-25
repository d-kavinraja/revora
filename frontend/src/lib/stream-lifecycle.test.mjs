import assert from 'node:assert/strict';
import test from 'node:test';

import { createMessage } from './chat-state.ts';
import { appendDelta, finalizeAssistant } from './chat-store-core.ts';
import { createDeltaBuffer, createStreamRegistry } from './stream-lifecycle.ts';

test('a new generation supersedes the previous token', () => {
  const registry = createStreamRegistry();
  assert.equal(registry.active(), null);
  const first = registry.begin('chat-a', 'msg-1');
  assert.equal(registry.isCurrent(first), true);
  assert.equal(registry.active(), first);
  const second = registry.begin('chat-a', 'msg-2');
  assert.equal(registry.isCurrent(first), false, 'the old stream lost its slot');
  assert.equal(registry.isCurrent(second), true);
  assert.notEqual(first.id, second.id);
  assert.equal(second.chatId, 'chat-a');
  assert.equal(second.messageId, 'msg-2');
  assert.ok(first.controller instanceof AbortController);
});

test('ending a stale token never clears the newer stream', () => {
  const registry = createStreamRegistry();
  const first = registry.begin('chat-a', 'msg-1');
  const second = registry.begin('chat-a', 'msg-2');
  assert.equal(registry.end(first), false);
  assert.equal(registry.isCurrent(second), true);
  assert.equal(registry.end(null), false);
  assert.equal(registry.end(second), true);
  assert.equal(registry.active(), null);
  assert.equal(registry.isCurrent(second), false, 'a finished token can never reopen');
  assert.equal(registry.end(second), false);
});

test('abort stops the active request and reports which one it was', () => {
  const registry = createStreamRegistry();
  assert.equal(registry.abort('chat-a'), null);
  const token = registry.begin('chat-a', 'msg-1');
  assert.equal(token.controller.signal.aborted, false);
  const aborted = registry.abort('chat-a');
  assert.equal(aborted, token);
  assert.equal(token.controller.signal.aborted, true);
  assert.equal(registry.active(), null);
  assert.equal(registry.isCurrent(token), false);
  assert.equal(registry.abort('chat-a'), null, 'a second abort is harmless');
  assert.equal(registry.abort('chat-missing'), null);
});

test('a late callback from a stopped generation cannot touch the store', () => {
  // Mirrors the shell: stop finalizes the message and ends the token, then the
  // parser delivers one more delta. Both the token guard and the status guard
  // must reject it, so the stopped answer cannot change afterwards.
  const registry = createStreamRegistry();
  const token = registry.begin('chat-a', 'msg-1');
  const buffer = createDeltaBuffer();
  let messages = [createMessage('user', 'q', 'complete', 1)];
  const placeholder = createMessage('assistant', '', 'streaming', 2);
  messages = [...messages, placeholder];

  buffer.push('Hel');
  buffer.push('lo');
  assert.equal(buffer.pending(), true);
  if (registry.isCurrent(token)) {
    messages = appendDelta(messages, placeholder.id, buffer.flush()) ?? messages;
  }
  assert.equal(messages[1].content, 'Hello');

  // Stop: flush whatever is buffered, finalize, then end the token.
  messages = appendDelta(messages, placeholder.id, buffer.flush()) ?? messages;
  messages = finalizeAssistant(messages, placeholder.id, 'stopped') ?? messages;
  registry.end(token);
  assert.equal(messages[1].status, 'stopped');

  // Late delta + late terminal event of the same generation.
  buffer.push(' more');
  if (registry.isCurrent(token)) {
    messages = appendDelta(messages, placeholder.id, buffer.flush()) ?? messages;
  }
  if (registry.isCurrent(token)) {
    messages = finalizeAssistant(messages, placeholder.id, 'complete', undefined, 'stop') ?? messages;
  }
  assert.equal(messages[1].content, 'Hello');
  assert.equal(messages[1].status, 'stopped');
  assert.equal(messages[1].finishReason, null);
});

test('chats stream independently and stopping one leaves the other alive', () => {
  const registry = createStreamRegistry();
  const a = registry.begin('chat-a', 'msg-a');
  const b = registry.begin('chat-b', 'msg-b');
  assert.deepEqual(registry.chatIds(), ['chat-a', 'chat-b']);
  assert.equal(registry.get('chat-a'), a);
  assert.equal(registry.get('chat-b'), b);
  assert.equal(registry.isCurrent(a), true, 'a second chat does not supersede the first');
  assert.equal(registry.isCurrent(b), true);

  // Each generation buffers its own text: a frame flushes both without mixing.
  a.buffer.push('alpha');
  b.buffer.push('beta');
  assert.equal(a.buffer.flush(), 'alpha');
  assert.equal(b.buffer.flush(), 'beta');

  const aborted = registry.abort('chat-a');
  assert.equal(aborted, a);
  assert.equal(a.controller.signal.aborted, true);
  assert.equal(b.controller.signal.aborted, false, 'chat-b keeps streaming');
  assert.equal(registry.isCurrent(a), false);
  assert.equal(registry.isCurrent(b), true);
  assert.deepEqual(registry.chatIds(), ['chat-b']);
  assert.equal(registry.active(), b);
});

test('abortAll stops every chat and reports each token once', () => {
  const registry = createStreamRegistry();
  const a = registry.begin('chat-a', 'msg-a');
  const b = registry.begin('chat-b', 'msg-b');
  const c = registry.begin('chat-c', 'msg-c');
  const tokens = registry.abortAll();
  assert.deepEqual(tokens.map((t) => t.chatId), ['chat-a', 'chat-b', 'chat-c']);
  assert.equal(a.controller.signal.aborted, true);
  assert.equal(b.controller.signal.aborted, true);
  assert.equal(c.controller.signal.aborted, true);
  assert.equal(registry.active(), null);
  assert.deepEqual(registry.chatIds(), []);
  assert.equal(registry.isCurrent(a), false);
  assert.deepEqual(registry.abortAll(), []);
});

test('ending one chat never ends another chat\'s generation', () => {
  const registry = createStreamRegistry();
  const a = registry.begin('chat-a', 'msg-a');
  const b = registry.begin('chat-b', 'msg-b');
  assert.equal(registry.end(a), true);
  assert.equal(registry.isCurrent(b), true);
  assert.equal(registry.get('chat-b'), b);
  assert.equal(registry.active(), b);
  assert.equal(registry.end(b), true);
  assert.equal(registry.active(), null);
});

test('delta buffering coalesces text and flushes exactly once', () => {
  const buffer = createDeltaBuffer();
  assert.equal(buffer.pending(), false);
  assert.equal(buffer.flush(), '');
  buffer.push('a');
  buffer.push('');
  buffer.push('bc');
  assert.equal(buffer.peek(), 'abc');
  assert.equal(buffer.pending(), true);
  assert.equal(buffer.flush(), 'abc');
  assert.equal(buffer.pending(), false);
  assert.equal(buffer.flush(), '', 'a second flush yields nothing');
  buffer.push('d');
  buffer.clear();
  assert.equal(buffer.pending(), false);
  assert.equal(buffer.peek(), '');
});
