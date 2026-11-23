import assert from 'node:assert/strict';
import test from 'node:test';

import {
  buildChatContext,
  buildRetryMessages,
  coalesceMetricsPatch,
  computeContextUsed,
  computePrefillPercent,
  computeTokensPerSecond,
  createChat,
  createInitialChatState,
  createMessage,
  deriveTitle,
  groupModels,
  isModelSelectable,
  isTruncatedFinish,
  pickDefaultModel,
} from './chat-state.ts';

test('createChat creates an empty temporary chat', () => {
  const chat = createChat('qwen3.8-27b', 100);
  assert.equal(chat.title, 'New chat');
  assert.equal(chat.model, 'qwen3.8-27b');
  assert.deepEqual(chat.messages, []);
  assert.equal(chat.createdAt, 100);
});

test('deriveTitle trims and truncates', () => {
  assert.equal(deriveTitle('  hello   world  '), 'hello world');
  assert.equal(deriveTitle(''), 'New chat');
  assert.match(deriveTitle('a'.repeat(60)), /…$/);
});

test('buildChatContext keeps only selected chat and excludes streaming/error messages', () => {
  const chatA = createChat('qwen3.8-27b');
  chatA.messages = [
    { ...createMessage('user', 'A1'), status: 'complete' },
    { ...createMessage('assistant', 'A2'), status: 'complete' },
    { ...createMessage('user', 'A3'), status: 'complete' },
    { ...createMessage('assistant', ''), status: 'streaming' },
    { ...createMessage('assistant', 'bad'), status: 'error' },
  ];
  const chatB = createChat('qwen3.8-27b');
  chatB.messages = [{ ...createMessage('user', 'B1'), status: 'complete' }];

  const ctxA = buildChatContext(chatA);
  assert.deepEqual(ctxA, [
    { role: 'user', content: 'A1' },
    { role: 'assistant', content: 'A2' },
    { role: 'user', content: 'A3' },
  ]);
  assert.equal(JSON.stringify(ctxA).includes('B1'), false);
});

test('buildChatContext trims to max messages/chars and keeps last user message', () => {
  const chat = createChat('qwen3.8-27b');
  for (let i = 0; i < 30; i += 1) {
    chat.messages.push({ ...createMessage('user', `u${i}-${'x'.repeat(2000)}`), status: 'complete' });
    chat.messages.push({ ...createMessage('assistant', `a${i}-${'y'.repeat(2000)}`), status: 'complete' });
  }
  const ctx = buildChatContext(chat, { maxMessages: 20, maxChars: 5000 });
  assert.ok(ctx.length <= 20);
  const total = ctx.reduce((s, m) => s + m.content.length, 0);
  assert.ok(total <= 5000);
  assert.equal(ctx.at(-1)?.role, 'user');
  assert.equal(ctx[0].role, 'user');
});

test('groupModels only marks ready models selectable', () => {
  const groups = groupModels([
    { key: 'ready', ready: true, readiness: 'ready', status: 'loaded' },
    { key: 'loading', ready: false, readiness: 'loading', status: 'loading' },
    { key: 'unloaded', ready: false, readiness: 'unloaded', status: 'unloaded' },
    { key: 'failed', ready: false, readiness: 'failed', status: 'failed' },
    { key: 'stale', ready: false, readiness: 'stale', status: 'loaded' },
  ]);
  assert.deepEqual(groups.ready.map((m) => m.key), ['ready']);
  assert.equal(isModelSelectable(groups.ready[0]), true);
  assert.equal(isModelSelectable(groups.loading[0]), false);
  assert.equal(isModelSelectable(groups.unloaded[0]), false);
  assert.equal(isModelSelectable(groups.failed[0]), false);
  assert.equal(isModelSelectable(groups.unavailable[0]), false);
});

test('pickDefaultModel keeps selected ready model or falls back to first ready', () => {
  const models = [
    { key: 'a', ready: true, readiness: 'ready' },
    { key: 'b', ready: true, readiness: 'ready' },
  ];
  assert.equal(pickDefaultModel(models, 'b'), 'b');
  assert.equal(pickDefaultModel(models, 'missing'), 'a');
  assert.equal(pickDefaultModel([{ key: 'x', ready: false, readiness: 'loading' }], 'x'), null);
});

test('createInitialChatState has one active chat', () => {
  const state = createInitialChatState(123);
  assert.equal(state.order.length, 1);
  assert.equal(state.activeId, state.order[0]);
  assert.ok(state.chats[state.order[0]]);
});

test('length finish reason is classified as truncation, not completion', () => {
  assert.equal(isTruncatedFinish('length'), true);
  assert.equal(isTruncatedFinish('max_tokens'), true);
  assert.equal(isTruncatedFinish('content_filter'), true);
  assert.equal(isTruncatedFinish('LENGTH'), true);
});

test('normal and unknown finish reasons are not misreported as failures', () => {
  assert.equal(isTruncatedFinish('stop'), false);
  assert.equal(isTruncatedFinish('end_turn'), false);
  assert.equal(isTruncatedFinish(null), false);
  assert.equal(isTruncatedFinish(undefined), false);
  assert.equal(isTruncatedFinish('some_future_reason'), false);
});

test('cancelled partial assistant responses are excluded from context', () => {
  const chat = createChat('m');
  chat.messages = [
    { ...createMessage('user', 'question'), status: 'complete' },
    { ...createMessage('assistant', 'partial answer'), status: 'stopped' },
    { ...createMessage('user', 'follow up'), status: 'complete' },
  ];
  const ctx = buildChatContext(chat);
  assert.deepEqual(ctx, [
    { role: 'user', content: 'question' },
    { role: 'user', content: 'follow up' },
  ]);
  assert.equal(ctx.some((m) => m.content === 'partial answer'), false);
});

test('prefill percent uses the native formula and rejects invalid values', () => {
  assert.equal(computePrefillPercent({ cache: 10, processed: 40, total: 80 }), 43);
  assert.equal(computePrefillPercent({ cache: 0, processed: 75, total: 100 }), 75);
  assert.equal(computePrefillPercent({ cache: 10, processed: 10, total: 80 }), 0);
  assert.equal(computePrefillPercent({ cache: 10, processed: 90, total: 80 }), null);
  assert.equal(computePrefillPercent({ cache: 10, processed: 40, total: 10 }), null);
  assert.equal(computePrefillPercent(null), null);
});

test('generation speed is derived from llama-server token and millisecond counts', () => {
  assert.equal(computeTokensPerSecond(12, 400), 30);
  assert.equal(computeTokensPerSecond(0, 400), null);
  assert.equal(computeTokensPerSecond(12, 0), null);
  assert.equal(computeTokensPerSecond(undefined, 400), null);
});

test('context usage sums new prompt, cached and generated tokens', () => {
  assert.equal(computeContextUsed({ prompt_n: 30, cache_n: 10, gen_n: 12 }), 52);
  assert.equal(computeContextUsed({ cache_n: 10 }), 10);
  assert.equal(computeContextUsed({}), null);
});

test('per-token telemetry coalesces into a single patch per paint', () => {
  let pending = null;
  for (let i = 1; i <= 60; i += 1) {
    pending = coalesceMetricsPatch(pending, 'msg-1', {
      phase: 'generating',
      outputTokens: i,
      genTps: i / 2,
    });
  }
  assert.equal(pending.messageId, 'msg-1');
  assert.equal(pending.patch.outputTokens, 60);
  assert.equal(pending.patch.genTps, 30);
  assert.equal(Object.keys(pending.patch).length, 3);

  const other = coalesceMetricsPatch(pending, 'msg-2', { phase: 'preparing' });
  assert.equal(other.messageId, 'msg-2');
  assert.deepEqual(other.patch, { phase: 'preparing' });
});

test('retry reuses the user turn and does not duplicate it', () => {
  const user = createMessage('user', 'explain reverse proxies', 'complete');
  const failed = createMessage('assistant', 'partial', 'error');
  const prepared = buildRetryMessages([user, failed], failed.id);
  assert.ok(prepared);
  assert.equal(prepared.content, 'explain reverse proxies');
  assert.equal(prepared.messages.filter((m) => m.role === 'user').length, 1);
  assert.equal(prepared.messages[0].id, user.id);
  assert.equal(prepared.messages[prepared.messages.length - 1].id, prepared.assistantMessageId);
  assert.equal(prepared.messages.some((m) => m.id === failed.id), false);
});
