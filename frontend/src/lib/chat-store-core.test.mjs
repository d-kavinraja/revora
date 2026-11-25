import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CHAT_MAX_MESSAGES_PER_CHAT,
  createMessage,
  planMessageEdit,
  planRegeneration,
} from './chat-state.ts';
import {
  appendDelta,
  applyEditPlan,
  applyRegenerationPlan,
  finalizeAssistant,
  reserveTurn,
  restoreSnapshot,
  setConfirmedModel,
} from './chat-store-core.ts';

const user = (content = 'question') => createMessage('user', content, 'complete', 1);
const reply = (extra = {}) =>
  createMessage('assistant', 'answer', 'complete', 2, {
    model: 'kllm:old',
    provider: 'kllm',
    ...extra,
  });
const ATTRIBUTED = {
  model: 'hosted-ollama:llama3',
  provider: 'hosted-ollama',
  upstreamModel: 'llama3:8b',
};

test('a turn reserves the prompt and its placeholder together', () => {
  const before = [user()];
  const result = reserveTurn(before, '  hello  ', { model: 'hosted-ollama:x', provider: 'hosted-ollama' }, 10);
  assert.equal(result.ok, true);
  assert.equal(result.messages.length, 3);
  assert.equal(result.messages[1].role, 'user');
  assert.equal(result.messages[1].content, 'hello');
  assert.equal(result.messages[2].role, 'assistant');
  assert.equal(result.messages[2].status, 'streaming');
  assert.equal(result.messages[2].model, 'hosted-ollama:x');
  assert.equal(result.messages[2].provider, 'hosted-ollama');
  assert.equal(result.userMessageId, result.messages[1].id);
  assert.equal(result.assistantMessageId, result.messages[2].id);
  assert.equal(result.messages[0], before[0]);
  // Reserved ids are stable, so a later delta can address the placeholder.
  assert.equal(result.messages.filter((m) => m.status === 'streaming').length, 1);
});

test('the last free slot refuses the whole turn instead of orphaning the prompt', () => {
  const full = [];
  for (let i = 0; i < CHAT_MAX_MESSAGES_PER_CHAT - 1; i += 1) {
    full.push(createMessage(i % 2 === 0 ? 'user' : 'assistant', `m${i}`, 'complete', 1));
  }
  assert.equal(full.length, 199);
  const result = reserveTurn(full, 'one more', undefined, 5);
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'chat_full');
  assert.equal(result.remaining, 1);
  assert.equal(full.length, 199, 'the refused turn never touches the history');
  assert.equal(full.some((m) => m.status === 'streaming'), false);

  // At the hard limit the refusal is the same, with no remaining slots.
  full.push(createMessage('user', 'last', 'complete', 1));
  const atLimit = reserveTurn(full, 'too late', undefined, 6);
  assert.equal(atLimit.ok, false);
  assert.equal(atLimit.reason, 'chat_full');
  assert.equal(atLimit.remaining, 0);
});

test('an empty prompt is refused without writing anything', () => {
  for (const content of ['', '   ', '\n\t']) {
    const result = reserveTurn([user()], content);
    assert.equal(result.ok, false);
    assert.equal(result.reason, 'empty');
  }
});

test('a matching regeneration plan is applied and stamped with the new model', () => {
  const messages = [user(), reply({ upstreamModel: 'kllm:old:latest', finishReason: 'stop' })];
  const plan = planRegeneration(messages, messages[1].id, { model: 'kllm:new', provider: 'kllm' });
  assert.ok(plan);
  const applied = applyRegenerationPlan(messages, plan, { model: 'kllm:new', provider: 'kllm' });
  assert.equal(applied.ok, true);
  const placeholder = applied.messages.at(-1);
  assert.equal(applied.messages.length, 2);
  assert.equal(placeholder.id, plan.assistantMessageId);
  assert.equal(placeholder.status, 'streaming');
  assert.equal(placeholder.model, 'kllm:new');
  assert.equal(placeholder.provider, 'kllm');
  assert.equal(placeholder.upstreamModel, null);
  assert.equal(placeholder.finishReason, null);
  // The user turn is reused, never duplicated (entries are copied, not shared).
  assert.equal(applied.messages.filter((m) => m.role === 'user').length, 1);
  assert.equal(applied.messages[0].id, messages[0].id);
  assert.equal(applied.messages[0].content, 'question');
});

test('a regeneration plan is refused once the history moved on', () => {
  const messages = [user(), reply()];
  const plan = planRegeneration(messages, messages[1].id);
  assert.ok(plan);
  const newer = [...messages, user('later question'), reply()];
  const stale = applyRegenerationPlan(newer, plan);
  assert.equal(stale.ok, false);
  assert.equal(stale.reason, 'stale_plan');
  // Applying the same plan twice cannot resurrect the replaced placeholder.
  const once = applyRegenerationPlan(messages, plan);
  assert.equal(once.ok, true);
  const twice = applyRegenerationPlan(once.messages, plan);
  assert.equal(twice.ok, false);
  assert.equal(twice.reason, 'stale_plan');
});

test('a regeneration is refused while another stream is generating', () => {
  const messages = [user(), reply()];
  const plan = planRegeneration(messages, messages[1].id);
  assert.ok(plan);
  const streaming = [...messages, createMessage('assistant', '', 'streaming', 3)];
  const result = applyRegenerationPlan(streaming, plan);
  assert.equal(result.ok, false);
  assert.equal(result.reason, 'stale_plan');
  const sameLength = [...plan.head, { ...plan.replaced[0], status: 'streaming' }];
  const busy = applyRegenerationPlan(sameLength, plan);
  assert.equal(busy.ok, false);
  assert.equal(busy.reason, 'generating');
});

test('undo restores a valid snapshot verbatim', () => {
  const snapshot = [user(), reply()];
  // The regenerated answer replaced the old one; the chat is idle.
  const current = [user(), createMessage('assistant', 'new answer', 'complete', 9)];
  const restored = restoreSnapshot(current, snapshot);
  assert.equal(restored.ok, true);
  assert.deepEqual(restored.messages, snapshot);
  assert.notEqual(restored.messages[0], snapshot[0], 'restored entries are copies');
});

test('undo is refused when the tail is no longer the regenerated answer', () => {
  const snapshot = [user(), reply()];
  const regenerated = [user(), createMessage('assistant', 'new answer', 'complete', 4)];
  const tailId = regenerated[1].id;
  const ok = restoreSnapshot(regenerated, snapshot, tailId);
  assert.equal(ok.ok, true);
  // A newer turn arrived after the regeneration: undo must not discard it.
  const moved = [...regenerated, user('later'), reply()];
  const stale = restoreSnapshot(moved, snapshot, tailId);
  assert.equal(stale.ok, false);
  assert.equal(stale.reason, 'stale_snapshot');
});

test('undo refuses snapshots that are empty, invalid, streaming or too long', () => {
  const current = [user(), reply()];
  assert.equal(restoreSnapshot(current, []).reason, 'empty_snapshot');
  assert.equal(restoreSnapshot(current, null).reason, 'empty_snapshot');
  assert.equal(
    restoreSnapshot(current, [{ ...user(), role: 'system' }]).reason,
    'invalid_snapshot',
  );
  assert.equal(
    restoreSnapshot(current, [{ ...user(), status: 'streaming' }]).reason,
    'invalid_snapshot',
  );
  assert.equal(
    restoreSnapshot(current, [{ ...user(), id: '' }]).reason,
    'invalid_snapshot',
  );
  const duplicated = user();
  assert.equal(
    restoreSnapshot(current, [duplicated, { ...reply(), id: duplicated.id }]).reason,
    'invalid_snapshot',
  );
  assert.equal(
    restoreSnapshot(current, [{ ...user(), createdAt: Number.NaN }]).reason,
    'invalid_snapshot',
  );
  const tooLong = Array.from({ length: CHAT_MAX_MESSAGES_PER_CHAT + 1 }, (_, i) =>
    createMessage(i % 2 === 0 ? 'user' : 'assistant', `m${i}`, 'complete', 1),
  );
  assert.equal(restoreSnapshot(current, tooLong).reason, 'snapshot_too_long');
  // The current conversation may still be generating when nothing is restored.
  assert.equal(
    restoreSnapshot([user(), createMessage('assistant', '', 'streaming', 1)], [user()]).reason,
    'generating',
  );
});

test('a delta only ever appends to the live placeholder', () => {
  const live = createMessage('assistant', 'Hello', 'streaming', 1);
  const messages = [user(), live];
  const next = appendDelta(messages, live.id, ' world');
  assert.ok(next);
  assert.equal(next[1].content, 'Hello world');
  assert.equal(messages[1].content, 'Hello', 'the input list is not mutated');
  assert.equal(appendDelta(messages, live.id, ''), null);
  assert.equal(appendDelta(messages, 'missing', 'x'), null);
  assert.equal(appendDelta(messages, messages[0].id, 'x'), null, 'user turns never stream');
  const finished = [{ ...live, status: 'stopped' }];
  assert.equal(appendDelta(finished, live.id, 'late'), null);
});

test('finalizing is one-shot and records the finish reason', () => {
  const live = createMessage('assistant', 'partial', 'streaming', 1);
  const messages = [user(), live];
  const done = finalizeAssistant(messages, live.id, 'truncated', undefined, 'length');
  assert.ok(done);
  assert.equal(done[1].status, 'truncated');
  assert.equal(done[1].finishReason, 'length');
  assert.equal(done[1].error, undefined);
  // A late event cannot overwrite the terminal status.
  assert.equal(finalizeAssistant(done, live.id, 'complete'), null);
  assert.equal(finalizeAssistant(messages, messages[0].id, 'complete'), null);
  const failed = finalizeAssistant(messages, live.id, 'error', 'boom');
  assert.ok(failed);
  assert.equal(failed[1].error, 'boom');
  assert.equal(failed[1].finishReason, null);
  const aborted = finalizeAssistant(messages, live.id, 'aborted', undefined, 'incomplete');
  assert.ok(aborted);
  assert.equal(aborted[1].finishReason, 'incomplete');
});

test('the confirmed upstream model is recorded only for assistant turns', () => {
  const live = createMessage('assistant', 'x', 'streaming', 1, {
    model: 'hosted-ollama:llama3',
    provider: 'hosted-ollama',
  });
  const messages = [user(), live];
  const confirmed = setConfirmedModel(messages, live.id, ' llama3:8b ');
  assert.ok(confirmed);
  assert.equal(confirmed[1].upstreamModel, 'llama3:8b');
  assert.equal(confirmed[1].model, 'hosted-ollama:llama3', 'the requested key is preserved');
  const cleared = setConfirmedModel(messages, live.id, null);
  assert.ok(cleared);
  assert.equal(cleared[1].upstreamModel, null);
  assert.equal(setConfirmedModel(messages, messages[0].id, 'x'), null);
  assert.equal(setConfirmedModel(messages, 'missing', 'x'), null);
});

/** Provenance must survive every terminal transition, not just the happy one. */
function streamingAnswer(overrides = {}) {
  return createMessage('assistant', '', 'streaming', 1, { ...ATTRIBUTED, ...overrides });
}

test('a stopped answer keeps the model it was requested from', () => {
  const live = streamingAnswer();
  const messages = [user(), live];
  const stopped = finalizeAssistant(appendDelta(messages, live.id, 'half a sen'), live.id, 'stopped');
  assert.ok(stopped);
  assert.equal(stopped[1].status, 'stopped');
  assert.equal(stopped[1].model, ATTRIBUTED.model);
  assert.equal(stopped[1].provider, ATTRIBUTED.provider);
  assert.equal(stopped[1].upstreamModel, ATTRIBUTED.upstreamModel);
});

test('a failed answer keeps its attribution instead of losing the model who failed', () => {
  const live = streamingAnswer();
  const failed = finalizeAssistant([user(), live], live.id, 'error', 'provider blew up');
  assert.ok(failed);
  assert.equal(failed[1].error, 'provider blew up');
  assert.equal(failed[1].model, ATTRIBUTED.model);
  assert.equal(failed[1].upstreamModel, ATTRIBUTED.upstreamModel);
});

test('a truncated answer keeps its attribution and reports the length stop', () => {
  const live = streamingAnswer();
  const truncated = finalizeAssistant([user(), live], live.id, 'truncated', undefined, 'length');
  assert.ok(truncated);
  assert.equal(truncated[1].finishReason, 'length');
  assert.equal(truncated[1].model, ATTRIBUTED.model);
  assert.equal(truncated[1].provider, ATTRIBUTED.provider);
});

test('undo restores the original answer with its own attribution', () => {
  const question = user();
  const earlier = createMessage('assistant', 'earlier', 'complete', 2, {
    model: 'kllm-model',
    provider: 'kllm',
    upstreamModel: 'kllm-model:latest',
    finishReason: 'stop',
  });
  const snapshot = [question, earlier];
  // The current conversation replaced that answer with a newer, unfinished one.
  const current = [...snapshot.slice(0, 1), user('newer question'), reply({ model: 'kllm:new' })];
  const restored = restoreSnapshot(current, snapshot, current.at(-1).id);
  assert.ok(restored.ok, restored.reason);
  assert.equal(restored.messages.length, 2);
  // The restored turn keeps its kLLM attribution: undo never re-labels history.
  assert.equal(restored.messages[1].model, 'kllm-model');
  assert.equal(restored.messages[1].upstreamModel, 'kllm-model:latest');
  assert.equal(restored.messages[1].finishReason, 'stop');
});

test('regeneration records the newly requested model, not the previous answer\'s', () => {
  const messages = [user(), createMessage('assistant', 'old', 'complete', 2, ATTRIBUTED)];
  const plan = planRegeneration(messages, messages[1].id, {
    model: 'kllm-model',
    provider: 'kllm',
    upstreamModel: 'kllm-model:latest',
  });
  assert.ok(plan);
  const applied = applyRegenerationPlan(messages, plan, {
    model: 'kllm-model',
    provider: 'kllm',
    upstreamModel: 'kllm-model:latest',
  });
  assert.ok(applied.ok, applied.reason);
  const placeholder = applied.messages.at(-1);
  assert.equal(placeholder.model, 'kllm-model');
  assert.equal(placeholder.provider, 'kllm');
  // Nothing is confirmed until the provider reports it.
  assert.equal(placeholder.upstreamModel, null);
  assert.equal(placeholder.finishReason, null);
  assert.equal(applied.messages[0].role, 'user');
  assert.equal(applied.messages[0].model, undefined);
});

test('an edit plan replaces the user turn in place and drops every later turn', () => {
  const first = user('first question');
  const target = user('typo question');
  const oldReply = reply();
  const laterQuestion = user('later question');
  const laterReply = reply();
  const messages = [first, target, oldReply, laterQuestion, laterReply];
  const plan = planMessageEdit(messages, target.id, '  fixed question  ', {
    model: 'hosted-ollama:llama3',
    provider: 'hosted-ollama',
  });
  assert.ok(plan);
  assert.equal(plan.content, 'fixed question');
  assert.equal(plan.replacedAnswer, oldReply);
  assert.deepEqual(plan.laterMessages, [laterQuestion, laterReply]);
  assert.equal(plan.discardedCount, 2);
  assert.equal(plan.laterTurnCount, 1);
  assert.equal(plan.isLast, false);
  assert.equal(plan.edited.id, target.id);
  assert.equal(plan.edited.createdAt, target.createdAt);
  assert.equal(plan.edited.content, 'fixed question');

  const applied = applyEditPlan(messages, plan, {
    model: 'hosted-ollama:llama3',
    provider: 'hosted-ollama',
  });
  assert.ok(applied.ok, applied.reason);
  assert.equal(applied.messages.length, 3);
  assert.equal(applied.messages[0].id, first.id);
  assert.equal(applied.messages[1].id, target.id);
  assert.equal(applied.messages[1].content, 'fixed question');
  assert.equal(applied.messages[2].role, 'assistant');
  assert.equal(applied.messages[2].status, 'streaming');
  assert.equal(applied.messages[2].model, 'hosted-ollama:llama3');
  assert.equal(applied.messages[2].upstreamModel, null);
  assert.equal(applied.messages.filter((m) => m.role === 'user').length, 2);
});

test('edit plans refuse a changed history or an in-flight chat', () => {
  const target = user('question');
  const oldReply = reply();
  const messages = [target, oldReply];
  const plan = planMessageEdit(messages, target.id, 'edited');
  assert.ok(plan);

  const changed = [user('different'), ...messages.slice(1)];
  assert.deepEqual(applyEditPlan(changed, plan), { ok: false, reason: 'stale_plan' });

  const streaming = [target, { ...oldReply, status: 'streaming' }];
  assert.deepEqual(applyEditPlan(streaming, plan), { ok: false, reason: 'generating' });

  assert.deepEqual(applyEditPlan(messages, { ...plan, content: '' }), {
    ok: false,
    reason: 'empty_plan',
  });
});

test('editing the last user turn needs no confirmation later turns', () => {
  const target = user('only question');
  const plan = planMessageEdit([target], target.id, 'revised');
  assert.ok(plan);
  assert.equal(plan.discardedCount, 0);
  assert.equal(plan.isLast, true);
  assert.equal(plan.messages.length, 2);
});

test('editing a completed final turn replaces its answer without removing a turn', () => {
  const question = user('question');
  const answer = reply();
  const plan = planMessageEdit([question, answer], question.id, 'revised');
  assert.ok(plan);
  assert.equal(plan.replacedAnswer, answer);
  assert.deepEqual(plan.laterMessages, []);
  assert.equal(plan.discardedCount, 0);
  assert.equal(plan.laterTurnCount, 0);
  assert.equal(plan.isLast, true);

  const applied = applyEditPlan([question, answer], plan);
  assert.ok(applied.ok, applied.reason);
  assert.equal(applied.messages.length, 2);
  assert.equal(applied.messages[0].content, 'revised');
  assert.equal(applied.messages[1].status, 'streaming');
  assert.notEqual(applied.messages[1].id, answer.id);
});
