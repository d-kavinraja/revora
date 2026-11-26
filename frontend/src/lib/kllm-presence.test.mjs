import assert from 'node:assert/strict';
import test from 'node:test';

import {
  generateBrowserSessionId,
  getBrowserSessionId,
  isPresenceActivityEvent,
  isRecentlyInteractive,
} from './kllm-presence.ts';

test('generates a non-empty session identifier', () => {
  assert.equal(typeof generateBrowserSessionId(), 'string');
  assert.ok(generateBrowserSessionId().length > 8);
});

test('uses secure random bytes when randomUUID is unavailable', () => {
  const originalCrypto = globalThis.crypto;
  Object.defineProperty(globalThis, 'crypto', {
    configurable: true,
    value: {
      getRandomValues(bytes) {
        bytes.fill(1);
        return bytes;
      },
    },
  });

  try {
    assert.match(
      generateBrowserSessionId(),
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
  } finally {
    Object.defineProperty(globalThis, 'crypto', {
      configurable: true,
      value: originalCrypto,
    });
  }
});

test('does not create browser storage during server rendering', () => {
  assert.equal(getBrowserSessionId(), null);
});

test('active window uses the most recent interaction', () => {
  assert.equal(isRecentlyInteractive(90_000, 100_000), true);
  assert.equal(isRecentlyInteractive(0, 200_000), false);
  assert.equal(isRecentlyInteractive(Number.NaN, 100_000), false);
  assert.equal(isRecentlyInteractive(90_000, 100_000, 5_000), false);
});

test('only real interaction events refresh activity', () => {
  assert.equal(isPresenceActivityEvent('pointerdown'), true);
  assert.equal(isPresenceActivityEvent('keydown'), true);
  assert.equal(isPresenceActivityEvent('focus'), true);
  assert.equal(isPresenceActivityEvent('heartbeat'), false);
  assert.equal(isPresenceActivityEvent('click'), false);
});
