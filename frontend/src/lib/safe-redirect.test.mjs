import assert from 'node:assert/strict';
import test from 'node:test';

import { isSafeInternalPath } from './safe-redirect.ts';

test('accepts rooted internal paths', () => {
  assert.equal(isSafeInternalPath('/dashboard'), true);
  assert.equal(isSafeInternalPath('/repositories/repo-1?tab=reviews'), true);
  assert.equal(isSafeInternalPath('/a/b/c#section'), true);
});

test('rejects absolute, protocol-relative and smuggled URLs', () => {
  assert.equal(isSafeInternalPath('https://evil.example'), false);
  assert.equal(isSafeInternalPath('//evil.example'), false);
  assert.equal(isSafeInternalPath('/\\evil.example'), false);
  assert.equal(isSafeInternalPath('javascript:alert(1)'), false);
  assert.equal(isSafeInternalPath('dashboard'), false);
});

test('rejects non-string values', () => {
  assert.equal(isSafeInternalPath(null), false);
  assert.equal(isSafeInternalPath(undefined), false);
  assert.equal(isSafeInternalPath(42), false);
  assert.equal(isSafeInternalPath({}), false);
});
