import assert from 'node:assert/strict';
import test from 'node:test';

import { createPresenceHeartbeatQueue } from './kllm-heartbeat-queue.ts';

const tick = () => Promise.resolve().then(() => Promise.resolve());

async function waitFor(predicate, timeoutMs = 1000) {
  const started = Date.now();
  while (!predicate()) {
    if (Date.now() - started > timeoutMs) {
      throw new Error('Timed out waiting for heartbeat queue');
    }
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

test('queues a deactivation while an active heartbeat is in flight', async () => {
  const calls = [];
  let releaseFirst;
  const firstGate = new Promise((resolve) => {
    releaseFirst = resolve;
  });

  const queue = createPresenceHeartbeatQueue(async (active) => {
    calls.push(active);
    if (calls.length === 1) await firstGate;
  });

  queue.request(true);
  await tick();
  assert.deepEqual(calls, [true]);
  assert.equal(queue.inFlight, true);

  queue.request(false);
  assert.equal(queue.pending, false);
  releaseFirst();
  await waitFor(() => calls.length === 2);

  assert.deepEqual(calls, [true, false]);
  assert.equal(queue.inFlight, false);
  assert.equal(queue.pending, null);
});

test('never overlaps heartbeat requests', async () => {
  const calls = [];
  let concurrent = 0;
  let maxConcurrent = 0;
  const releases = [];

  const queue = createPresenceHeartbeatQueue(async (active) => {
    calls.push(active);
    concurrent += 1;
    maxConcurrent = Math.max(maxConcurrent, concurrent);
    await new Promise((resolve) => releases.push(resolve));
    concurrent -= 1;
  });

  queue.request(true);
  queue.request(false);
  queue.request(true);
  await tick();

  assert.deepEqual(calls, [true]);
  const firstRelease = releases.shift();
  assert.ok(firstRelease);
  firstRelease();
  await waitFor(() => calls.length === 2);
  const secondRelease = releases.shift();
  assert.ok(secondRelease);
  secondRelease();
  await waitFor(() => queue.inFlight === false);

  assert.deepEqual(calls, [true, true]);
  assert.equal(maxConcurrent, 1);
});

test('visibility returning to visible replaces a queued deactivation', async () => {
  const calls = [];
  let releaseFirst;
  const firstGate = new Promise((resolve) => {
    releaseFirst = resolve;
  });

  const queue = createPresenceHeartbeatQueue(async (active) => {
    calls.push(active);
    if (calls.length === 1) await firstGate;
  });

  queue.request(true);
  await tick();
  queue.request(false);
  queue.request(true);
  releaseFirst();
  await waitFor(() => calls.length === 2);

  assert.deepEqual(calls, [true, true]);
  assert.equal(queue.desired, true);
});

test('stop prevents queued deactivation after unmount', async () => {
  const calls = [];
  let releaseFirst;
  const firstGate = new Promise((resolve) => {
    releaseFirst = resolve;
  });

  const queue = createPresenceHeartbeatQueue(async (active) => {
    calls.push(active);
    if (calls.length === 1) await firstGate;
  });

  queue.request(true);
  await tick();
  queue.request(false);
  queue.stop();
  releaseFirst();
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.deepEqual(calls, [true]);
  assert.equal(queue.pending, null);
});

test('failed heartbeat still drains the newest queued state', async () => {
  const calls = [];
  const queue = createPresenceHeartbeatQueue(async (active) => {
    calls.push(active);
    if (calls.length === 1) throw new Error('transient network failure');
  });

  queue.request(true);
  await tick();
  queue.request(false);
  await waitFor(() => calls.length === 2);

  assert.deepEqual(calls, [true, false]);
  assert.equal(queue.inFlight, false);
});
