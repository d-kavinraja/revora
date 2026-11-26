import assert from 'node:assert/strict';
import test from 'node:test';

import {
  applyIncompleteMarker,
  buildChatContext,
  buildRetryMessages,
  canonicalModelKey,
  coalesceMetricsPatch,
  computeContextUsed,
  computePrefillPercent,
  computeTokensPerSecond,
  contextBudget,
  contextCharBudget,
  contextOutputReserve,
  maxOutputTokensForWindow,
  nextRequestContextMeter,
  resolveRequestOutputTokens,
  MIN_CONTEXT_INPUT_TOKENS,
  createChat,
  createEmptyChatState,
  createInitialChatState,
  createMessage,
  deriveTitle,
  editPrompt,
  editUndoNotice,
  enforceAlternation,
  fallbackModelForKey,
  finalStatusFor,
  groupModels,
  groupCatalogModels,
  getActiveChat,
  incompleteMarker,
  INCOMPLETE_MARKERS,
  isClippedContent,
  isContextEligible,
  isHostedModel,
  isIncompleteFinish,
  messageAttribution,
  finishNotice,
  clipMessageContent,
  formatContextWindow,
  modelDisplayName,
  modelFamily,
  modelProviderSlug,
  stripModelRoutingPrefix,
  undoNotice,
  upsertChatOrder,
  withPendingChatDraft,
  regenerationPrompt,
  CONTEXT_CLIP_MARKER,
  CHARS_PER_TOKEN_FIT,
  DEFAULT_CONTEXT_OUTPUT_TOKENS,
  MAX_CONTEXT_OUTPUT_TOKENS,
  INCOMPLETE_FINISH_REASON,
  TRUNCATION_MESSAGE,
  isModelSelectable,
  isTruncatedFinish,
  KLLM_MANAGEMENT_LABEL,
  managementLabelForModel,
  pickDefaultModel,
  planMessageEdit,
  planRegeneration,
  providerForKey,
  providerLabel,
  readinessReason,
  resolveSelectedModel,
  responseModelIdentity,
  CHAT_CONTEXT_CHARS_GLOBAL,
  CHAT_CONTEXT_MESSAGES_GLOBAL,
  HOSTED_PROVIDER,
  HOSTED_CATEGORY_LABEL,
  KLLM_PROVIDER,
  REVORA_MANAGEMENT_LABEL,
  HOSTED_PROVIDER_LABEL,
  KLLM_PROVIDER_LABEL,
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

test('buildChatContext keeps the selected chat and drops the stream placeholder', () => {
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
    { key: 'verifying', ready: false, readiness: 'verifying', status: 'verifying' },
    { key: 'unloaded', ready: false, readiness: 'unloaded', status: 'unloaded' },
    { key: 'failed', ready: false, readiness: 'failed', status: 'failed' },
    { key: 'stale', ready: false, readiness: 'stale', status: 'loaded' },
  ]);
  assert.deepEqual(groups.ready.map((m) => m.key), ['ready']);
  assert.deepEqual(groups.verifying.map((m) => m.key), ['verifying']);
  assert.equal(isModelSelectable(groups.ready[0]), true);
  assert.equal(isModelSelectable(groups.loading[0]), false);
  assert.equal(isModelSelectable(groups.verifying[0]), false);
  assert.equal(isModelSelectable(groups.unloaded[0]), false);
  assert.equal(isModelSelectable(groups.failed[0]), false);
  assert.equal(isModelSelectable(groups.unavailable[0]), false);
});

test('pickDefaultModel never replaces an existing selection', () => {
  const models = [
    { key: 'a', ready: true, readiness: 'ready' },
    { key: 'b', ready: true, readiness: 'ready' },
  ];
  assert.equal(pickDefaultModel(models, 'b'), 'b');
  // A selection is preserved even when it is no longer ready or missing:
  // a catalog refresh must never silently switch model or provider.
  assert.equal(pickDefaultModel(models, 'missing'), 'missing');
  assert.equal(pickDefaultModel([{ key: 'x', ready: false, readiness: 'loading' }], 'x'), 'x');
  // A default is only chosen when the chat has no selection at all.
  assert.equal(pickDefaultModel(models, null), 'a');
  assert.equal(pickDefaultModel([], null), null);
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

test('stopped partial responses stay in history with an outbound-only marker', () => {
  const chat = createChat('m');
  const stopped = { ...createMessage('assistant', 'partial answer'), status: 'stopped' };
  chat.messages = [
    { ...createMessage('user', 'question'), status: 'complete' },
    stopped,
    { ...createMessage('user', 'follow up'), status: 'complete' },
  ];
  const ctx = buildChatContext(chat);
  assert.deepEqual(ctx.map((m) => m.role), ['user', 'assistant', 'user']);
  assert.equal(ctx[1].content, 'partial answer\n\n[response stopped before it finished]');
  // The marker is outbound only: the stored turn keeps exactly what was shown.
  assert.equal(stopped.content, 'partial answer');
});

test('truncated, aborted and failed turns keep their partial content', () => {
  const chat = createChat('m');
  chat.messages = [
    { ...createMessage('user', 'q1'), status: 'complete' },
    { ...createMessage('assistant', 'cut'), status: 'truncated' },
    { ...createMessage('user', 'q2'), status: 'complete' },
    { ...createMessage('assistant', 'interrupted'), status: 'aborted' },
    { ...createMessage('user', 'q3'), status: 'complete' },
    { ...createMessage('assistant', 'failed'), status: 'error' },
    { ...createMessage('user', 'q4'), status: 'complete' },
  ];
  const ctx = buildChatContext(chat);
  assert.equal(ctx.length, 7);
  assert.match(ctx[1].content, /generation limit/);
  assert.match(ctx[3].content, /interrupted/);
  assert.match(ctx[5].content, /failed/);
});

test('empty terminal turns and the streaming placeholder are omitted', () => {
  const chat = createChat('m');
  chat.messages = [
    { ...createMessage('user', 'q1'), status: 'complete' },
    { ...createMessage('assistant', ''), status: 'error' },
    { ...createMessage('assistant', '   '), status: 'aborted' },
    { ...createMessage('assistant', ''), status: 'streaming' },
    { ...createMessage('user', 'q2'), status: 'complete' },
  ];
  assert.deepEqual(buildChatContext(chat), [
    { role: 'user', content: 'q1' },
    { role: 'user', content: 'q2' },
  ]);
});

test('isContextEligible only rejects the in-flight placeholder', () => {
  assert.equal(isContextEligible('streaming'), false);
  for (const status of ['complete', 'stopped', 'truncated', 'aborted', 'error']) {
    assert.equal(isContextEligible(status), true);
  }
  assert.equal(incompleteMarker('complete'), null);
  assert.equal(applyIncompleteMarker('x', 'complete'), 'x');
  assert.equal(applyIncompleteMarker('x', 'stopped'), `x\n\n${INCOMPLETE_MARKERS.stopped}`);
  assert.equal(
    applyIncompleteMarker(applyIncompleteMarker('x', 'stopped'), 'stopped'),
    `x\n\n${INCOMPLETE_MARKERS.stopped}`,
  );
});

test('finalStatusFor maps truncation to a distinct terminal status', () => {
  assert.equal(finalStatusFor('stop'), 'complete');
  assert.equal(finalStatusFor('length'), 'truncated');
  assert.equal(finalStatusFor('content_filter'), 'truncated');
  assert.equal(isTruncatedFinish('length'), true);
  assert.equal(isTruncatedFinish('stop'), false);
});

test('a missing terminal reason is an interrupted answer, not a clean finish', () => {
  // A stream that ends without `done` must never be reported as complete.
  assert.equal(finalStatusFor(null), 'aborted');
  assert.equal(finalStatusFor(undefined), 'aborted');
  assert.equal(finalStatusFor(''), 'aborted');
  assert.equal(finalStatusFor('  '), 'aborted');
  assert.equal(finalStatusFor(INCOMPLETE_FINISH_REASON), 'aborted');
  assert.equal(isIncompleteFinish(null), true);
  assert.equal(isIncompleteFinish(''), true);
  assert.equal(isIncompleteFinish('stop'), false);
  assert.equal(isIncompleteFinish('length'), false);
});

test('the finish notice distinguishes every terminal cause', () => {
  assert.equal(
    finishNotice({ status: 'truncated', finishReason: 'length' }),
    TRUNCATION_MESSAGE,
  );
  assert.match(
    finishNotice({ status: 'truncated', finishReason: 'content_filter' }) ?? '',
    /safety filter/,
  );
  assert.match(
    finishNotice({ status: 'aborted', finishReason: INCOMPLETE_FINISH_REASON }) ?? '',
    /closed before the model reported completion/,
  );
  assert.match(finishNotice({ status: 'stopped' }) ?? '', /stopped/);
  assert.equal(finishNotice({ status: 'error', error: 'boom' }), 'boom');
  assert.equal(finishNotice({ status: 'error' }), 'Response failed.');
  assert.equal(finishNotice({ status: 'complete' }), null);
  assert.equal(finishNotice({ status: 'streaming' }), null);
});

test('undo and regeneration wording never invent removed messages', () => {
  assert.match(undoNotice(0), /previous answer can be restored/);
  assert.doesNotMatch(undoNotice(0), /0 later/);
  assert.match(undoNotice(1), /1 later message was removed/);
  assert.match(undoNotice(3), /3 later messages were removed/);
  assert.match(regenerationPrompt(0), /No later messages will be removed/);
  assert.match(regenerationPrompt(1), /removes 1 later message/);
  assert.match(regenerationPrompt(4), /removes 4 later messages/);
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

test('isHostedModel detects provider and category', () => {
  assert.equal(isHostedModel({ key: 'hosted-ollama:qwen3:1.7b', provider: 'hosted-ollama' }), true);
  assert.equal(isHostedModel({ key: 'x', category: 'hosted' }), true);
  assert.equal(isHostedModel({ key: 'qwen3.8-27b', provider: 'kllm' }), false);
  assert.equal(isHostedModel(null), false);
});

test('hosted runtime-loaded model is selectable', () => {
  const hosted = {
    key: 'hosted-ollama:qwen3:1.7b-q4_K_M',
    provider: 'hosted-ollama',
    category: 'hosted',
    ready: true,
    readiness: 'ready',
    resident: true,
  };
  assert.equal(isModelSelectable(hosted), true);
});

test('groupCatalogModels partitions by provider then readiness', () => {
  const models = [
    { key: 'qwen3.8-27b', provider: 'kllm', ready: true, readiness: 'ready' },
    { key: 'hosted-ollama:qwen3:1.7b', provider: 'hosted-ollama', ready: true, readiness: 'ready' },
    { key: 'hosted-ollama:llama3:8b', provider: 'hosted-ollama', ready: false, readiness: 'unloaded' },
    { key: 'kllm-loading', provider: 'kllm', ready: false, readiness: 'loading' },
  ];
  const groups = groupCatalogModels(models);
  assert.equal(groups.kllm.ready.length, 1);
  assert.equal(groups.hosted.ready.length, 1);
  assert.equal(groups.hosted.unloaded.length, 1);
  assert.equal(groups.kllm.loading.length, 1);
  assert.equal(groups.hosted.ready[0].key, 'hosted-ollama:qwen3:1.7b');
});

test('hosted category label is the managed-by-Revora wording', () => {
  assert.equal(HOSTED_CATEGORY_LABEL, 'Hosted models managed by Revora');
  assert.equal(HOSTED_PROVIDER_LABEL, 'Hosted Models');
  assert.equal(KLLM_PROVIDER_LABEL, 'kLLM');
});

test('provider sections are derived from backend identity, not hardcoded names', () => {
  assert.equal(providerLabel({ key: 'hosted-ollama:a', provider: 'hosted-ollama' }), HOSTED_PROVIDER_LABEL);
  assert.equal(providerLabel({ key: 'b', provider: 'kllm' }), KLLM_PROVIDER_LABEL);
  assert.equal(providerForKey('hosted-ollama:a'), 'hosted-ollama');
  // Legacy hosted spelling and an explicit kLLM prefix route consistently.
  assert.equal(providerForKey('hosted_ollama:a'), 'hosted-ollama');
  assert.equal(providerForKey('kllm:qwen3'), 'kllm');
  assert.equal(providerForKey('qwen3.8-27b'), 'kllm');
  assert.equal(providerForKey(null), 'kllm');
});

test('canonicalModelKey sends one backend key without rewriting history', () => {
  assert.equal(canonicalModelKey('hosted-ollama:llama3'), 'hosted-ollama:llama3');
  assert.equal(canonicalModelKey('hosted_ollama:llama3'), 'hosted-ollama:llama3');
  assert.equal(canonicalModelKey('kllm:qwen3'), 'qwen3');
  assert.equal(canonicalModelKey('qwen3'), 'qwen3');
  assert.equal(canonicalModelKey('  '), '');
});

test('hosted installed-but-unloaded models stay visible and disabled', () => {
  const groups = groupCatalogModels([
    { key: 'hosted-ollama:a', provider: 'hosted-ollama', ready: true, readiness: 'ready' },
    {
      key: 'hosted-ollama:b',
      provider: 'hosted-ollama',
      ready: false,
      readiness: 'unloaded',
      installed: true,
      admin_loadable: true,
      reason_code: 'model_not_loaded',
    },
  ]);
  assert.deepEqual(groups.hosted.ready.map((m) => m.key), ['hosted-ollama:a']);
  assert.deepEqual(groups.hosted.unloaded.map((m) => m.key), ['hosted-ollama:b']);
  assert.equal(isModelSelectable(groups.hosted.unloaded[0]), false);
  assert.match(readinessReason(groups.hosted.unloaded[0]), /not loaded/i);
  assert.equal(readinessReason(groups.hosted.ready[0]), null);
});

test('readiness reason falls back to the tracked load operation state', () => {
  assert.match(readinessReason({ key: 'k', ready: false, readiness: 'loading', load_state: 'verifying' }), /verifying/i);
  assert.equal(readinessReason(null), null);
});

test('the context budget follows the model window and the global ceiling', () => {
  assert.equal(contextCharBudget(null), 240_000);
  assert.equal(contextCharBudget(0), 240_000);
  assert.equal(contextCharBudget(8192), (8192 - 2_048 - 2_048) * 3);
  assert.equal(contextCharBudget(1_000_000), CHAT_CONTEXT_CHARS_GLOBAL);
  assert.equal(contextCharBudget(131_072, 16_384), (131_072 - 16_384 - 2_048) * 3);
  assert.equal(contextBudget(131_072).maxMessages, CHAT_CONTEXT_MESSAGES_GLOBAL);
  assert.equal(contextBudget(131_072).windowed, true);
  assert.equal(contextBudget(null).windowed, false);
});

test('the unknown-window fallback is explicit instead of silently applied', () => {
  for (const unknown of [null, undefined, 0, Number.NaN]) {
    const budget = contextBudget(unknown);
    assert.equal(budget.fallback, true);
    assert.equal(budget.maxMessages, 20);
    assert.equal(budget.maxChars, 240_000);
    assert.equal(budget.outputTokens, DEFAULT_CONTEXT_OUTPUT_TOKENS);
  }
  // A known window never reports the fallback, and keeps a real prompt allowance.
  for (const window of [2_048, 4_096, 8_192, 32_768, 131_072]) {
    const budget = contextBudget(window);
    assert.equal(budget.fallback, false);
    assert.ok(budget.maxChars >= 1);
    assert.ok(window - budget.outputTokens - budget.headroom >= MIN_CONTEXT_INPUT_TOKENS);
    assert.ok(budget.outputTokens >= 1);
    assert.ok(budget.maxChars <= CHAT_CONTEXT_CHARS_GLOBAL);
  }
});

test('an explicit max_tokens is clamped to the window before fitting', () => {
  // 60k output tokens cannot fit an 8k window; the request is clamped, not sent.
  assert.equal(contextOutputReserve(8_192, 60_000), maxOutputTokensForWindow(8_192));
  assert.equal(contextBudget(8_192, 60_000).outputTokens, maxOutputTokensForWindow(8_192));
  assert.ok(contextBudget(8_192, 60_000).outputTokens < 60_000);
  // A sane override is honoured, and the prompt allowance follows it.
  assert.equal(contextOutputReserve(131_072, 8_192), 8_192);
  assert.equal(contextBudget(131_072, 8_192).maxChars, (131_072 - 8_192 - 2_048) * CHARS_PER_TOKEN_FIT);
  // The default reserve stays inside the hard output ceiling.
  assert.equal(contextOutputReserve(131_072, null), MAX_CONTEXT_OUTPUT_TOKENS);
  assert.equal(contextBudget(8_192).outputTokens, 2_048);
});

test('an oversized newest message keeps its head, its tail and one marker', () => {
  const chat = createChat('m');
  const instruction = 'INSTRUCTION: summarise the trace below.';
  const tail = 'END-OF-TRACE';
  chat.messages.push({
    ...createMessage('user', `${instruction}${'x'.repeat(40_000)}${tail}`),
    status: 'complete',
  });
  const budget = contextBudget(8_192);
  const ctx = buildChatContext(chat, { contextWindow: 8_192 });
  assert.equal(ctx.length, 1);
  const content = ctx[0].content;
  assert.ok(content.length <= budget.maxChars);
  assert.ok(content.startsWith(instruction), 'the instruction survives at the head');
  assert.ok(content.endsWith(tail), 'the end of the pasted content survives');
  assert.equal(isClippedContent(content), true);
  assert.equal(content.split(CONTEXT_CLIP_MARKER).length - 1, 1);
  // Refitting an already clipped copy is idempotent and never adds a marker.
  assert.equal(clipMessageContent(content, budget.maxChars), content);
  // The stored message keeps the full text: clipping is outbound only.
  assert.ok(chat.messages[0].content.endsWith(tail));
  assert.equal(chat.messages[0].content.length, instruction.length + 40_000 + tail.length);
});

test('a budget too small for the marker keeps the beginning rather than nothing', () => {
  const clipped = clipMessageContent('abcdefghijklmnopqrstuvwxyz', 10);
  assert.equal(clipped, 'abcdefghij');
  assert.equal(isClippedContent(clipped), false);
});

test('a large model window keeps the whole conversation instead of 20 turns', () => {
  const chat = createChat('m');
  for (let i = 0; i < 60; i += 1) {
    chat.messages.push({ ...createMessage('user', `q${i} ` + 'x'.repeat(10)), status: 'complete' });
    chat.messages.push({ ...createMessage('assistant', `a${i} ` + 'y'.repeat(10)), status: 'complete' });
  }
  chat.messages.push({ ...createMessage('user', 'final question'), status: 'complete' });
  const ctx = buildChatContext(chat, { contextWindow: 131_072 });
  assert.equal(ctx.length, 121);
  assert.equal(ctx.at(-1).content, 'final question');
});

test('a small model window keeps the newest contiguous turns inside the budget', () => {
  const chat = createChat('m');
  for (let i = 0; i < 30; i += 1) {
    chat.messages.push({ ...createMessage('user', `q${i} ` + 'x'.repeat(1000)), status: 'complete' });
    chat.messages.push({ ...createMessage('assistant', `a${i} ` + 'y'.repeat(1000)), status: 'complete' });
  }
  chat.messages.push({ ...createMessage('user', 'final question'), status: 'complete' });
  const ctx = buildChatContext(chat, { contextWindow: 8192 });
  const budget = contextBudget(8192).maxChars;
  assert.ok(ctx.length > 0 && ctx.length < chat.messages.length);
  assert.ok(ctx.reduce((sum, m) => sum + m.content.length, 0) <= budget);
  assert.equal(ctx.at(-1).content, 'final question');
  assert.equal(ctx[0].role, 'user');
});

test('an unknown window keeps the fixed fallback caps', () => {
  const chat = createChat('m');
  for (let i = 0; i < 60; i += 1) {
    chat.messages.push({ ...createMessage('user', `q${i}`), status: 'complete' });
    chat.messages.push({ ...createMessage('assistant', `a${i}`), status: 'complete' });
  }
  chat.messages.push({ ...createMessage('user', 'final'), status: 'complete' });
  const ctx = buildChatContext(chat);
  assert.ok(ctx.length <= 20);
  assert.equal(ctx.at(-1).content, 'final');
});

test('changing the selected model only widens or narrows the window, never the order', () => {
  const chat = createChat('m');
  for (let i = 0; i < 30; i += 1) {
    chat.messages.push({ ...createMessage('user', `q${i} ` + 'x'.repeat(200)), status: 'complete' });
    chat.messages.push({ ...createMessage('assistant', `a${i} ` + 'y'.repeat(200)), status: 'complete' });
  }
  chat.messages.push({ ...createMessage('user', 'last'), status: 'complete' });
  const wide = buildChatContext(chat, { contextWindow: 131_072 });
  const narrow = buildChatContext(chat, { contextWindow: 4096 });
  assert.ok(narrow.length < wide.length);
  assert.deepEqual(
    narrow.map((m) => m.content),
    wide.slice(wide.length - narrow.length).map((m) => m.content),
  );
  assert.equal(wide.at(-1).content, 'last');
});

test('the same stored history reaches both providers in the same order', () => {
  const chat = createChat('m');
  chat.messages = [
    { ...createMessage('user', 'q1'), status: 'complete' },
    { ...createMessage('assistant', 'a1'), status: 'complete' },
    { ...createMessage('user', 'q2'), status: 'complete' },
  ];
  const kllm = buildChatContext(chat, { contextWindow: 131_072 });
  const hosted = buildChatContext(chat, { contextWindow: 131_072, strictAlternation: true });
  assert.deepEqual(hosted, kllm);
  assert.deepEqual(kllm.map((m) => m.role), ['user', 'assistant', 'user']);
});

test('fitting never mutates the stored conversation', () => {
  const chat = createChat('m');
  for (let i = 0; i < 10; i += 1) {
    chat.messages.push({ ...createMessage('user', `q${i} ` + 'x'.repeat(500)), status: 'complete' });
    chat.messages.push({ ...createMessage('assistant', `a${i}`), status: 'stopped' });
  }
  const snapshot = JSON.stringify(chat.messages);
  buildChatContext(chat, { contextWindow: 4096 });
  assert.equal(JSON.stringify(chat.messages), snapshot);
});

test('strict alternation merges same-role turns without losing text', () => {
  const chat = createChat('m');
  chat.messages = [
    { ...createMessage('user', 'question'), status: 'complete' },
    { ...createMessage('assistant', 'partial answer'), status: 'stopped' },
    { ...createMessage('user', 'follow up'), status: 'complete' },
  ];
  // kLLM: the partial answer keeps the turn list alternating on its own.
  assert.deepEqual(
    buildChatContext(chat).map((m) => m.role),
    ['user', 'assistant', 'user'],
  );
  // Hosted: alternating input passes through with the same content.
  const hosted = buildChatContext(chat, { strictAlternation: true });
  assert.deepEqual(hosted.map((m) => m.role), ['user', 'assistant', 'user']);
  assert.match(hosted[1].content, /^partial answer/);
  // Consecutive user turns are merged for hosted prompt templates.
  const consecutive = createChat('m');
  consecutive.messages = [
    { ...createMessage('user', 'first'), status: 'complete' },
    { ...createMessage('user', 'second'), status: 'complete' },
  ];
  assert.deepEqual(buildChatContext(consecutive, { strictAlternation: true }), [
    { role: 'user', content: 'first\n\nsecond' },
  ]);
  assert.deepEqual(
    enforceAlternation([
      { role: 'user', content: 'a' },
      { role: 'user', content: 'b' },
      { role: 'assistant', content: 'c' },
      { role: 'assistant', content: 'd' },
      { role: 'user', content: 'e' },
    ]).map((m) => m.role),
    ['user', 'assistant', 'user'],
  );
});

test('regenerating the last turn discards no messages', () => {
  const user = createMessage('user', 'question', 'complete');
  const answer = createMessage('assistant', 'answer', 'complete');
  const plan = planRegeneration([user, answer], answer.id);
  assert.ok(plan);
  assert.equal(plan.discardedCount, 0);
  assert.equal(plan.isLast, true);
  assert.equal(plan.replaced.length, 1);
  assert.equal(plan.messages.length, 2);
  assert.equal(plan.messages.at(-1).status, 'streaming');
  assert.equal(plan.messages.some((m) => m.id === answer.id), false);
  assert.equal(plan.messages.filter((m) => m.role === 'user').length, 1);
  assert.equal(plan.content, 'question');
  assert.equal(plan.userId, user.id);
});

test('regenerating an older turn reports the exact discarded count', () => {
  const messages = [
    createMessage('user', 'q1', 'complete'),
    createMessage('assistant', 'a1', 'complete'),
    createMessage('user', 'q2', 'complete'),
    createMessage('assistant', 'a2', 'complete'),
    createMessage('user', 'q3', 'complete'),
    createMessage('assistant', 'a3', 'complete'),
  ];
  const plan = planRegeneration(messages, messages[1].id);
  assert.ok(plan);
  assert.equal(plan.discardedCount, 4);
  assert.equal(plan.isLast, false);
  // head ends at the user prompt that produced the response.
  assert.equal(plan.head.length, 1);
  assert.equal(plan.previous, messages);
  assert.equal(plan.messages.length, 2);
  // Planning is pure: nothing in the stored conversation changed.
  assert.equal(messages.length, 6);
  assert.equal(messages[1].content, 'a1');
  assert.equal(messages[1].status, 'complete');
  // Undo restores the exact pre-regeneration list.
  assert.deepEqual(plan.previous, messages);
});

test('regeneration accepts every terminal assistant status but not streaming', () => {
  for (const status of ['complete', 'error', 'stopped', 'truncated', 'aborted']) {
    const user = createMessage('user', 'q', 'complete');
    const reply = { ...createMessage('assistant', 'partial', 'complete'), status };
    const plan = planRegeneration([user, reply], reply.id);
    assert.ok(plan, status);
    assert.equal(plan.messages.filter((m) => m.role === 'user').length, 1);
  }
  const user = createMessage('user', 'q', 'complete');
  const streaming = createMessage('assistant', '', 'streaming');
  assert.equal(planRegeneration([user, streaming], streaming.id), null);
});

test('regeneration is rejected for an orphan assistant or an unknown message', () => {
  const orphan = createMessage('assistant', 'a', 'complete');
  assert.equal(planRegeneration([orphan], orphan.id), null);
  assert.equal(planRegeneration([createMessage('user', 'q')], 'missing'), null);
});

test('assistant attribution shows the requested and the confirmed model honestly', () => {
  const plain = createMessage('assistant', 'ok', 'complete', 1, {
    model: 'qwen3.8-27b',
    provider: 'kllm',
  });
  const kllm = messageAttribution(plain);
  assert.equal(kllm.provider, 'kllm');
  assert.equal(kllm.requested, 'qwen3.8-27b');
  assert.equal(kllm.confirmed, null);
  assert.equal(kllm.label, 'kllm · qwen3.8-27b');
  assert.match(kllm.title, /Requested: qwen3\.8-27b/);
  assert.match(kllm.title, /Confirmed by provider: not reported/);

  const hosted = createMessage('assistant', 'ok', 'complete', 1, {
    model: 'hosted-ollama:llama3',
    provider: 'hosted-ollama',
  });
  // The hosted prefix is stripped from the label, never from the record.
  assert.equal(messageAttribution(hosted).label, 'hosted-ollama · llama3');

  const confirmed = { ...hosted, upstreamModel: 'llama3:8b' };
  const differs = messageAttribution(confirmed);
  assert.equal(differs.confirmed, 'llama3:8b');
  assert.equal(differs.label, 'hosted-ollama · llama3:8b (requested llama3)');
  assert.match(differs.title, /Confirmed by provider: llama3:8b/);

  // User turns never carry attribution, and a message without provenance shows none.
  assert.equal(messageAttribution(createMessage('user', 'hi')).label, null);
  assert.equal(messageAttribution(createMessage('assistant', 'x')).label, null);
});

test('attribution and routing agree for every accepted prefix', () => {
  for (const key of ['hosted-ollama:llama3', 'hosted_ollama:llama3']) {
    const message = createMessage('assistant', 'ok', 'complete', 1, { model: key });
    assert.equal(providerForKey(key), 'hosted-ollama');
    const attribution = messageAttribution(message);
    assert.equal(attribution.provider, 'hosted-ollama');
    assert.equal(attribution.label, 'hosted-ollama · llama3');
    assert.equal(attribution.requested, key);
  }
  const kllm = createMessage('assistant', 'ok', 'complete', 1, { model: 'kllm:qwen3' });
  assert.equal(providerForKey('kllm:qwen3'), 'kllm');
  assert.equal(messageAttribution(kllm).label, 'kllm · qwen3');
  assert.equal(canonicalModelKey('kllm:qwen3'), 'qwen3');
});

test('provenance is stamped per answer and never rewritten in place', () => {
  const user = createMessage('user', 'q');
  const older = createMessage('assistant', 'old answer', 'complete', 1, {
    model: 'hosted-ollama:llama3',
    provider: 'hosted-ollama',
    upstreamModel: 'llama3:latest',
  });
  const plan = planRegeneration([user, older], older.id, { model: 'kllm:new', provider: 'kllm' });
  assert.ok(plan);
  const placeholder = plan.messages.at(-1);
  assert.equal(placeholder.model, 'kllm:new');
  assert.equal(placeholder.provider, 'kllm');
  assert.equal(placeholder.upstreamModel, undefined);
  // The previous answer keeps its own attribution for undo.
  assert.equal(plan.previous.at(-1).model, 'hosted-ollama:llama3');
  assert.equal(plan.previous.at(-1).upstreamModel, 'llama3:latest');
  // A user turn carries no model, provider or upstream id at all.
  assert.equal('model' in user, false);
  assert.equal('provider' in user, false);
});

test('user and unanswered turns never claim a model', () => {
  const question = createMessage('user', 'hello');
  const attribution = messageAttribution(question);
  assert.equal(attribution.provider, null);
  assert.equal(attribution.requested, null);
  assert.equal(attribution.confirmed, null);
  assert.equal(attribution.label, null);
  assert.equal(attribution.title, null);
  // An assistant turn whose model is unknown shows no invented label either.
  const bare = createMessage('assistant', 'answer');
  assert.equal(messageAttribution(bare).label, null);
  assert.equal(messageAttribution(bare).title, null);
});

test('attribution stays local and is never sent upstream', () => {
  const chat = createChat('hosted-ollama:llama3');
  const answered = createMessage('assistant', 'the answer', 'complete', 2, {
    model: 'hosted-ollama:llama3',
    provider: 'hosted-ollama',
    upstreamModel: 'llama3:8b',
    finishReason: 'stop',
  });
  chat.messages = [createMessage('user', 'a question'), answered];
  const context = buildChatContext(chat, { contextWindow: 8192 });
  // Only role and content leave the browser: no model id, no provider, no label.
  for (const entry of context) {
    assert.deepEqual(Object.keys(entry).sort(), ['content', 'role']);
    assert.ok(!/llama3|hosted-ollama|Requested:|Confirmed/i.test(entry.content));
  }
  // The stored answer keeps its attribution for the bubble.
  assert.equal(chat.messages[1].upstreamModel, 'llama3:8b');
  assert.equal(chat.messages[1].provider, 'hosted-ollama');
});

test('pickDefaultModel can select a hosted model when it is the only ready one', () => {
  const models = [
    { key: 'hosted-ollama:qwen3:1.7b', provider: 'hosted-ollama', ready: true, readiness: 'ready' },
  ];
  assert.equal(pickDefaultModel(models, null), 'hosted-ollama:qwen3:1.7b');
});

test('the resolved output budget matches the backend golden table', () => {
  const message = [{ content: 'x'.repeat(3000) }];
  const cases = [
    [null, 4096],
    [2000, 500],
    [8000, 2000],
    [32000, 4096],
    [128000, 4096],
    [200000, 4096],
  ];
  for (const [window, expected] of cases) {
    assert.equal(resolveRequestOutputTokens(window, message), expected, `window ${window}`);
  }
  // A tiny prompt leaves the reserve dominant, not the remaining room.
  assert.equal(resolveRequestOutputTokens(2000, [{ content: 'hi' }]), 1024);
  // The unknown-window path keeps the request inside the hard ceiling.
  assert.equal(resolveRequestOutputTokens(null, [], 60_000), MAX_CONTEXT_OUTPUT_TOKENS);
  assert.equal(resolveRequestOutputTokens(undefined, [], 0), 1);
});

test('an empty new chat reports zero prompt usage, not the reply reserve', () => {
  const chat = createChat('kllm:small');
  const meter = nextRequestContextMeter(chat, 4096);
  assert.equal(meter.messages, 0);
  assert.equal(meter.promptTokens, 0);
  assert.equal(meter.usedTokens, 0);
  assert.equal(meter.usedPct, 0);
  assert.equal(meter.remaining, 4096);
  // The budget still exists, but it is reserved output/headroom, not usage.
  assert.equal(meter.outputTokens, 1024);
  assert.equal(meter.headroom, 1024);
  assert.equal(meter.nextRequestTokens, 2048);
  assert.equal(meter.nextRequestFits, true);
  assert.equal(meter.spareAfterNextRequest, 2048);
});

test('the context meter counts the next request of one chat only', () => {
  const small = createChat('kllm:small');
  small.messages = [
    { ...createMessage('user', 'hi'), status: 'complete' },
    { ...createMessage('assistant', 'hello'), status: 'complete' },
    { ...createMessage('user', 'next question'), status: 'complete' },
  ];
  const large = createChat('kllm:small');
  large.messages = [
    { ...createMessage('user', 'q ' + 'x'.repeat(4000)), status: 'complete' },
    { ...createMessage('assistant', 'a ' + 'y'.repeat(4000)), status: 'complete' },
    { ...createMessage('user', 'final'), status: 'complete' },
  ];

  const a = nextRequestContextMeter(small, 32_768);
  const b = nextRequestContextMeter(large, 32_768);
  assert.ok(a.promptTokens > 0);
  assert.ok(b.promptTokens > a.promptTokens, 'another chat never contributes to this meter');
  assert.equal(a.usedTokens, a.promptTokens);
  assert.equal(a.usedPct, Math.min(100, Math.round((a.promptTokens / 32_768) * 1000) / 10));
  assert.equal(a.remaining, 32_768 - a.promptTokens);
  assert.equal(a.nextRequestTokens, a.promptTokens + a.outputTokens + a.headroom);
  assert.equal(a.nextRequestFits, true);
  assert.equal(a.spareAfterNextRequest, 32_768 - a.nextRequestTokens);
  assert.equal(a.fallback, false);
  assert.equal(a.contextWindow, 32_768);
  assert.equal(a.messages, buildChatContext(small, { contextWindow: 32_768 }).length);
});

test('a previous response usage is secondary and never the meter numerator', () => {
  const chat = createChat('kllm:small');
  chat.messages = [
    { ...createMessage('user', 'question'), status: 'complete' },
    { ...createMessage('assistant', 'answer'), status: 'complete' },
    { ...createMessage('user', 'follow up'), status: 'complete' },
  ];
  const plain = nextRequestContextMeter(chat, 8192);
  const withHistory = nextRequestContextMeter(chat, 8192, { historicalTokens: 7000 });
  assert.equal(withHistory.usedTokens, plain.usedTokens);
  assert.equal(withHistory.usedPct, plain.usedPct);
  assert.equal(withHistory.remaining, plain.remaining);
  assert.equal(withHistory.historicalTokens, 7000);
  assert.equal(plain.historicalTokens, null);
});

test('an unknown window labels the meter as an estimate without guessing a denominator', () => {
  const chat = createChat('kllm:small');
  chat.messages = [{ ...createMessage('user', 'hello'), status: 'complete' }];
  const meter = nextRequestContextMeter(chat, null, { historicalTokens: 123 });
  assert.equal(meter.fallback, true);
  assert.equal(meter.contextWindow, null);
  assert.equal(meter.usedPct, null);
  assert.equal(meter.remaining, null);
  assert.equal(meter.outputTokens, DEFAULT_CONTEXT_OUTPUT_TOKENS);
  assert.equal(meter.usedTokens, meter.promptTokens);
  assert.equal(meter.nextRequestFits, null);
  assert.equal(meter.spareAfterNextRequest, null);
  assert.equal(meter.historicalTokens, 123);
});

test('the meter follows the selected model window for the same chat', () => {
  const chat = createChat('kllm:small');
  for (let i = 0; i < 20; i += 1) {
    chat.messages.push({ ...createMessage('user', `q${i} ` + 'x'.repeat(300)), status: 'complete' });
    chat.messages.push({ ...createMessage('assistant', `a${i} ` + 'y'.repeat(300)), status: 'complete' });
  }
  const narrow = nextRequestContextMeter(chat, 4096);
  const wide = nextRequestContextMeter(chat, 131_072);
  assert.ok(narrow.promptTokens <= wide.promptTokens);
  assert.ok(wide.messages >= narrow.messages);
  assert.equal(wide.contextWindow, 131_072);
  assert.equal(narrow.contextWindow, 4096);
  assert.ok(narrow.usedPct > wide.usedPct);
});

test('one message keeps prompt usage separate from reserve and headroom', () => {
  const chat = createChat('kllm:small');
  chat.messages = [{ ...createMessage('user', 'x'.repeat(300)), status: 'complete' }];
  const meter = nextRequestContextMeter(chat, 4096);
  assert.equal(meter.messages, 1);
  assert.equal(meter.promptTokens, 100);
  assert.equal(meter.usedTokens, 100);
  assert.equal(meter.usedPct, 2.4);
  assert.equal(meter.outputTokens, 1024);
  assert.equal(meter.headroom, 1024);
  assert.equal(meter.nextRequestTokens, 2148);
  assert.equal(meter.remaining, 3996);
  assert.equal(meter.nextRequestFits, true);
  assert.equal(meter.spareAfterNextRequest, 1948);
});

test('multiple messages contribute only to their own chat', () => {
  const a = createChat('kllm:small');
  a.messages = [
    { ...createMessage('user', 'a'.repeat(300)), status: 'complete' },
    { ...createMessage('assistant', 'b'.repeat(300)), status: 'complete' },
    { ...createMessage('user', 'c'.repeat(300)), status: 'complete' },
  ];
  const b = createChat('kllm:small');
  b.messages = [{ ...createMessage('user', 'z'.repeat(60)), status: 'complete' }];
  const meterA = nextRequestContextMeter(a, 32_768);
  const meterB = nextRequestContextMeter(b, 32_768);
  assert.equal(meterA.promptTokens, 300);
  assert.equal(meterB.promptTokens, 20);
  assert.equal(meterA.messages, 3);
  assert.equal(meterB.messages, 1);
  assert.equal(meterA.usedTokens, 300);
  assert.equal(meterB.usedTokens, 20);
});

test('switching chats never reuses another chat\'s context estimate', () => {
  const long = createChat('kllm:small');
  for (let i = 0; i < 10; i += 1) {
    long.messages.push({ ...createMessage('user', `q${i}-` + 'x'.repeat(290)), status: 'complete' });
    long.messages.push({ ...createMessage('assistant', `a${i}-` + 'y'.repeat(290)), status: 'complete' });
  }
  const empty = createChat('kllm:small');
  const state = {
    chats: { [long.id]: long, [empty.id]: empty },
    order: [empty.id, long.id],
    activeId: long.id,
    drafts: {},
    streaming: {},
  };
  const longBefore = nextRequestContextMeter(getActiveChat(state), 32_768);
  state.activeId = empty.id;
  const emptyMeter = nextRequestContextMeter(getActiveChat(state), 32_768);
  assert.ok(longBefore.promptTokens > 0);
  assert.equal(emptyMeter.promptTokens, 0);
  assert.equal(emptyMeter.usedPct, 0);
  assert.equal(emptyMeter.messages, 0);
  // Returning to the long chat must restore exactly its own estimate.
  state.activeId = long.id;
  assert.deepEqual(nextRequestContextMeter(getActiveChat(state), 32_768), longBefore);
});

test('different model windows recalculate the same chat', () => {
  const chat = createChat('kllm:small');
  for (let i = 0; i < 12; i += 1) {
    chat.messages.push({ ...createMessage('user', `q${i}-` + 'x'.repeat(290)), status: 'complete' });
    chat.messages.push({ ...createMessage('assistant', `a${i}-` + 'y'.repeat(290)), status: 'complete' });
  }
  const small = nextRequestContextMeter(chat, 4096);
  const large = nextRequestContextMeter(chat, 131_072);
  assert.equal(small.contextWindow, 4096);
  assert.equal(large.contextWindow, 131_072);
  assert.ok(small.promptTokens > 0);
  assert.ok(small.promptTokens <= large.promptTokens);
  assert.ok(small.usedPct !== null && large.usedPct !== null);
  assert.ok(small.usedPct > large.usedPct);
  assert.ok(small.outputTokens <= large.outputTokens);
  assert.equal(small.nextRequestFits, true);
  assert.equal(large.nextRequestFits, true);
});

test('a model switch in another chat does not change this chat\'s meter', () => {
  const a = createChat('kllm:small');
  a.messages = [{ ...createMessage('user', 'x'.repeat(300)), status: 'complete' }];
  const b = createChat('kllm:small');
  b.messages = [{ ...createMessage('user', 'y'.repeat(600)), status: 'complete' }];
  const aBefore = nextRequestContextMeter(a, 4096);
  const bBefore = nextRequestContextMeter(b, 4096);
  b.model = 'kllm:large';
  assert.deepEqual(nextRequestContextMeter(a, 4096), aBefore);
  assert.notDeepEqual(nextRequestContextMeter(b, 32_768), bBefore);
});

test('a new chat starts clean without clearing the long chat', () => {
  const long = createChat('kllm:small');
  long.messages = [{ ...createMessage('user', 'x'.repeat(30_000)), status: 'complete' }];
  const longMeter = nextRequestContextMeter(long, 32_768);
  const state = {
    chats: { [long.id]: long },
    order: [long.id],
    activeId: long.id,
    drafts: {},
    streaming: {},
  };
  const fresh = createChat(long.model);
  const next = {
    ...state,
    chats: { ...state.chats, [fresh.id]: fresh },
    order: upsertChatOrder(state.order, fresh.id),
    activeId: fresh.id,
  };
  assert.equal(next.chats[long.id], long);
  assert.deepEqual(next.order, [fresh.id, long.id]);
  const freshMeter = nextRequestContextMeter(getActiveChat(next), 32_768);
  assert.ok(longMeter.promptTokens > 0);
  assert.equal(fresh.messages.length, 0);
  assert.equal(freshMeter.messages, 0);
  assert.equal(freshMeter.promptTokens, 0);
  assert.equal(freshMeter.usedTokens, 0);
  assert.equal(freshMeter.usedPct, 0);
  assert.equal(freshMeter.remaining, 32_768);
  assert.equal(freshMeter.historicalTokens, null);
  // The previous chat is untouched and still reports its own prompt.
  assert.deepEqual(nextRequestContextMeter(long, 32_768), longMeter);
});

test('model display names strip only known internal routing prefixes', () => {
  assert.equal(stripModelRoutingPrefix('hosted-ollama:llama3.2:3b'), 'llama3.2:3b');
  assert.equal(stripModelRoutingPrefix('hosted_ollama:llama3.2:3b'), 'llama3.2:3b');
  assert.equal(stripModelRoutingPrefix('kllm:qwen2.5:7b'), 'qwen2.5:7b');
  assert.equal(stripModelRoutingPrefix('meta-llama/Llama-3.2-3B'), 'meta-llama/Llama-3.2-3B');
  assert.equal(stripModelRoutingPrefix(null), '');
});

test('modelDisplayName prefers the backend display name and cleans both fields', () => {
  assert.equal(modelDisplayName({ key: 'hosted-ollama:llama3.2:3b' }), 'llama3.2:3b');
  assert.equal(
    modelDisplayName({
      key: 'hosted-ollama:llama3.2:3b',
      display_name: 'Llama 3.2 3B',
    }),
    'Llama 3.2 3B',
  );
  assert.equal(
    modelDisplayName({
      key: 'hosted-ollama:llama3.2:3b',
      display_name: 'hosted-ollama:Llama 3.2 3B',
    }),
    'Llama 3.2 3B',
  );
  assert.equal(modelDisplayName(null), '');
});

test('modelFamily detects the families with available brand icons', () => {
  assert.equal(modelFamily({ key: 'hosted-ollama:llama3.2:3b' }), 'meta');
  assert.equal(modelFamily({ key: 'hosted-ollama:qwen2.5:7b' }), 'qwen');
  assert.equal(modelFamily({ key: 'hosted-ollama:gemma2:2b' }), 'gemma');
  assert.equal(modelFamily({ key: 'hosted-ollama:mistral:7b' }), 'mistral');
  assert.equal(modelFamily({ key: 'hosted-ollama:deepseek-r1:7b' }), 'deepseek');
  assert.equal(modelFamily({ key: 'hosted-ollama:unknown:1b' }), null);
});

test('modelProviderSlug falls back to the provider for unrecognised families', () => {
  assert.equal(modelProviderSlug({ key: 'hosted-ollama:unknown:1b' }), 'ollama');
  assert.equal(modelProviderSlug({ provider: HOSTED_PROVIDER, key: 'unknown:1b' }), 'ollama');
  assert.equal(modelProviderSlug({ provider: 'hosted_ollama', key: 'unknown:1b' }), 'ollama');
  assert.equal(modelProviderSlug({ category: 'hosted', key: 'unknown:1b' }), 'ollama');
  assert.equal(modelProviderSlug({ key: 'qwen2.5:7b' }), 'kllm');
  assert.equal(modelProviderSlug(null), 'kllm');
});

test('unknown-family admin models keep their real provider brand', () => {
  assert.equal(modelProviderSlug({ key: 'gpt-4o', provider: 'openai' }), 'openai');
  assert.equal(modelProviderSlug({ key: 'gemini-2.5-pro', provider: 'gemini' }), 'gemini');
  assert.equal(modelProviderSlug({ key: 'claude-3-5-sonnet', provider: 'anthropic' }), 'anthropic');
  assert.equal(modelProviderSlug({ key: 'command-r', provider: 'cohere' }), 'cohere');
  assert.equal(modelProviderSlug({ key: 'custom', provider: 'kllm' }), 'kllm');
});

test('a stale selected key keeps an equivalent, unavailable identity', () => {
  const fallback = fallbackModelForKey('hosted_ollama:legacy:7b');
  assert.equal(fallback.key, 'hosted_ollama:legacy:7b');
  assert.equal(fallback.display_name, 'legacy:7b');
  assert.equal(fallback.provider, HOSTED_PROVIDER);
  assert.equal(fallback.category, 'hosted');
  assert.equal(fallback.reason_code, 'not_in_catalog');
  assert.equal(isModelSelectable(fallback), false);

  const catalog = [
    { key: 'hosted-ollama:llama3', provider: HOSTED_PROVIDER, display_name: 'llama3' },
    { key: 'qwen3', provider: KLLM_PROVIDER },
  ];
  // Canonical matching lets a legacy stored key find its live row.
  assert.equal(resolveSelectedModel(catalog, 'hosted_ollama:llama3')?.display_name, 'llama3');
  assert.equal(resolveSelectedModel(catalog, 'kllm:qwen3')?.key, 'qwen3');
  // A truly missing key still resolves to the same fallback identity.
  assert.equal(resolveSelectedModel(catalog, 'hosted-ollama:gone')?.reason_code, 'not_in_catalog');
  assert.equal(resolveSelectedModel(catalog, null), null);
});

test('formatContextWindow renders a compact K label and rejects invalid values', () => {
  assert.equal(formatContextWindow(4096), '4K');
  assert.equal(formatContextWindow(131_072), '128K');
  assert.equal(formatContextWindow(0), null);
  assert.equal(formatContextWindow(null), null);
  assert.equal(formatContextWindow(Number.NaN), null);
});

test('modelFamily detects Phi models without matching unrelated names', () => {
  assert.equal(modelFamily({ key: 'hosted-ollama:phi4-mini:3.8b' }), 'microsoft');
  assert.equal(modelFamily({ key: 'phi3' }), 'microsoft');
  assert.equal(modelFamily({ key: 'phi' }), 'microsoft');
  assert.equal(modelFamily({ key: 'phi-3.5' }), 'microsoft');
  assert.equal(modelFamily({ key: 'phidata' }), null);
});

test('management labels follow provider routing', () => {
  assert.equal(
    managementLabelForModel({ key: 'hosted-ollama:llama3.2:3b' }),
    REVORA_MANAGEMENT_LABEL,
  );
  assert.equal(managementLabelForModel({ key: 'qwen2.5:7b' }), KLLM_MANAGEMENT_LABEL);
  assert.equal(managementLabelForModel({ key: 'phi4-mini:3.8b' }), KLLM_MANAGEMENT_LABEL);
});

test('planMessageEdit replaces a user turn and records the discarded tail', () => {
  const first = createMessage('user', 'earlier', 'complete', 1);
  const target = createMessage('user', 'old question', 'complete', 2);
  const answer = createMessage('assistant', 'old answer', 'complete', 3, {
    model: 'hosted-ollama:llama3',
  });
  const later = createMessage('user', 'later question', 'complete', 4);
  const messages = [first, target, answer, later];

  const plan = planMessageEdit(messages, target.id, '  new question  ', {
    model: 'hosted-ollama:llama3',
    provider: 'hosted-ollama',
  });
  assert.ok(plan);
  assert.equal(plan.content, 'new question');
  assert.equal(plan.originalContent, 'old question');
  assert.equal(plan.edited.id, target.id);
  assert.equal(plan.edited.createdAt, target.createdAt);
  assert.equal(plan.messages.length, 3);
  assert.equal(plan.messages[0].id, first.id);
  assert.equal(plan.messages[1].id, target.id);
  assert.equal(plan.messages[2].role, 'assistant');
  assert.equal(plan.messages[2].status, 'streaming');
  assert.equal(plan.messages[2].model, 'hosted-ollama:llama3');
  assert.deepEqual(plan.replaced, [answer, later]);
  assert.equal(plan.replacedAnswer, answer);
  assert.deepEqual(plan.laterMessages, [later]);
  assert.equal(plan.discardedCount, 1);
  assert.equal(plan.laterTurnCount, 1);
  assert.equal(plan.isLast, false);
  assert.deepEqual(plan.previous, messages);
});

test('editing a completed final turn replaces only its answer without a removal warning', () => {
  const question = createMessage('user', 'question', 'complete', 1);
  const answer = createMessage('assistant', 'answer', 'complete', 2);
  const plan = planMessageEdit([question, answer], question.id, 'revised');
  assert.ok(plan);
  assert.equal(plan.replacedAnswer, answer);
  assert.deepEqual(plan.laterMessages, []);
  assert.equal(plan.discardedCount, 0);
  assert.equal(plan.laterTurnCount, 0);
  assert.equal(plan.isLast, true);
  assert.equal(plan.messages.length, 2);
});

test('edit planning counts later conversation turns, not raw messages', () => {
  const messages = [
    createMessage('user', 'q1', 'complete', 1),
    createMessage('assistant', 'a1', 'complete', 2),
    createMessage('user', 'q2', 'complete', 3),
    createMessage('assistant', 'a2', 'complete', 4),
    createMessage('user', 'q3', 'complete', 5),
    createMessage('assistant', 'a3', 'complete', 6),
  ];
  const plan = planMessageEdit(messages, messages[0].id, 'revised');
  assert.ok(plan);
  assert.deepEqual(plan.laterMessages, messages.slice(2));
  // Two later user prompts, even though four later messages are removed.
  assert.equal(plan.laterTurnCount, 2);
  assert.equal(plan.discardedCount, 4);
  assert.equal(plan.isLast, false);
});

test('planMessageEdit refuses empty edits and non-user or streaming messages', () => {
  const userMessage = createMessage('user', 'question', 'complete', 1);
  const assistantMessage = createMessage('assistant', 'answer', 'complete', 2);
  const streaming = createMessage('user', 'pending', 'streaming', 3);
  const messages = [userMessage, assistantMessage, streaming];

  assert.equal(planMessageEdit(messages, userMessage.id, '   '), null);
  assert.equal(planMessageEdit(messages, 'missing-id', 'edit'), null);
  assert.equal(planMessageEdit(messages, assistantMessage.id, 'edit'), null);
  assert.equal(planMessageEdit(messages, streaming.id, 'edit'), null);
});

test('edit wording never claims removals that did not happen', () => {
  assert.match(editPrompt(0), /new answer/i);
  assert.doesNotMatch(editPrompt(0), /remove/i);
  assert.match(editPrompt(1), /1 later turn/);
  assert.match(editPrompt(3), /3 later turns/);
  assert.match(editUndoNotice(0), /previous answer can be restored/i);
  assert.match(editUndoNotice(1), /1 later turn was removed/i);
  assert.match(editUndoNotice(3), /3 later turns were removed/i);
});

test('a hosted SmolLM response identity matches the dropdown item', () => {
  const message = {
    role: 'assistant',
    model: 'hosted-ollama:smollm:135m',
    provider: 'hosted-ollama',
    upstreamModel: 'smollm:135m',
  };
  const response = responseModelIdentity(message, 'smollm:135m');
  const dropdown = {
    key: 'hosted-ollama:smollm:135m',
    display_name: 'smollm:135m',
    provider: 'hosted-ollama',
  };

  assert.ok(response);
  assert.equal(response.key, dropdown.key);
  assert.equal(response.display_name, dropdown.display_name);
  assert.equal(response.provider, dropdown.provider);
  assert.equal(response.category, 'hosted');
  assert.equal(modelProviderSlug(response), modelProviderSlug(dropdown));
  assert.equal(modelProviderSlug(response), 'ollama');
  assert.equal(modelFamily(response), modelFamily(dropdown));
  assert.equal(modelDisplayName(response), 'smollm:135m');
  assert.equal(managementLabelForModel(response), REVORA_MANAGEMENT_LABEL);
});

test('response identity uses provenance when telemetry only has a bare model id', () => {
  const message = {
    role: 'assistant',
    model: 'hosted-ollama:smollm:360m',
    provider: 'hosted-ollama',
    upstreamModel: null,
  };
  const response = responseModelIdentity(message, 'smollm:360m');
  assert.ok(response);
  assert.equal(modelProviderSlug(response), 'ollama');
  assert.equal(modelDisplayName(response), 'smollm:360m');
  assert.equal(modelFamily(response), 'huggingface');

  const kllm = responseModelIdentity(
    { role: 'assistant', model: 'qwen2.5:7b', provider: 'kllm', upstreamModel: null },
    'qwen2.5:7b',
  );
  assert.ok(kllm);
  assert.equal(modelProviderSlug(kllm), 'kllm');
  assert.equal(managementLabelForModel(kllm), KLLM_MANAGEMENT_LABEL);
});

test('modelFamily maps SmolLM models to Hugging Face', () => {
  assert.equal(modelFamily({ key: 'hosted-ollama:smollm:135m' }), 'huggingface');
  assert.equal(modelFamily({ key: 'smollm:360m' }), 'huggingface');
  assert.equal(modelFamily({ display_name: 'SmolLM 135M' }), 'huggingface');
  assert.equal(modelFamily({ key: 'llama3.2:3b' }), 'meta');
});

test('the initial chat state is deterministic so SSR and hydration agree', () => {
  const first = createEmptyChatState();
  const second = createEmptyChatState();
  assert.deepEqual(first, second);
  assert.deepEqual(first.order, []);
  assert.equal(first.activeId, null);
  assert.deepEqual(first.chats, {});
  assert.deepEqual(first.drafts, {});
  assert.deepEqual(first.streaming, {});
});

test('the unsent draft participates in the next-request context estimate', () => {
  const chat = createChat('model', 1);
  chat.messages = [createMessage('user', 'stored question', 'complete', 2)];
  const withoutDraft = nextRequestContextMeter(chat, 8192);
  const withDraft = withPendingChatDraft(chat, 'a longer follow up question');
  const withDraftMeter = nextRequestContextMeter(withDraft, 8192);

  assert.equal(withDraft.messages.length, chat.messages.length + 1);
  assert.ok(withDraftMeter.promptTokens > withoutDraft.promptTokens);
  assert.equal(withDraftMeter.messages, withoutDraft.messages + 1);
  // The estimate never mutates the stored conversation.
  assert.equal(chat.messages.length, 1);
});

test('persistent context meters stay isolated per conversation', () => {
  const makePersistentChat = (id, content) => ({
    ...createChat('model', 1),
    id,
    messages: content
      ? [createMessage('user', content, 'complete', 2)]
      : [],
  });
  const long = makePersistentChat('conversation-a', 'x'.repeat(3_000));
  const short = makePersistentChat('conversation-b', 'short question');
  const empty = makePersistentChat('conversation-c', '');
  const options = { includeIncompleteMarkers: false };

  const longMeter = nextRequestContextMeter(long, 8192, options);
  const shortMeter = nextRequestContextMeter(short, 8192, options);
  const emptyMeter = nextRequestContextMeter(empty, 8192, options);

  assert.ok(longMeter.promptTokens > shortMeter.promptTokens);
  assert.ok(shortMeter.promptTokens > emptyMeter.promptTokens);
  assert.equal(emptyMeter.promptTokens, 0);
  assert.equal(emptyMeter.messages, 0);
  // Revisiting a conversation after switching away reproduces only its own meter.
  assert.deepEqual(nextRequestContextMeter(short, 8192, options), shortMeter);
  assert.deepEqual(nextRequestContextMeter(long, 8192, options), longMeter);
  assert.notDeepEqual(nextRequestContextMeter(short, 131_072, options), shortMeter);
});

test('the persistent meter excludes in-memory markers the backend never sends', () => {
  const chat = createChat('model', 1);
  chat.messages = [
    createMessage('user', 'question', 'complete', 2),
    createMessage('assistant', 'partial answer', 'stopped', 3),
    createMessage('user', 'follow up', 'complete', 4),
  ];
  const outgoing = buildChatContext(chat);
  const persistent = buildChatContext(chat, { includeIncompleteMarkers: false });
  assert.equal(outgoing.length, 3);
  assert.match(outgoing[1].content, /stopped before it finished/);
  assert.equal(persistent[1].content, 'partial answer');

  const withMarkers = nextRequestContextMeter(chat, 8192);
  const withoutMarkers = nextRequestContextMeter(chat, 8192, { includeIncompleteMarkers: false });
  assert.ok(withMarkers.promptTokens >= withoutMarkers.promptTokens);
  assert.equal(withoutMarkers.historicalTokens, null);
});
