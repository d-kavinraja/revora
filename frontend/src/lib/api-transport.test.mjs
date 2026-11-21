import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import {
  apiErrorMessage,
  isApiTransportError,
  normalizeBackendOrigin,
  resolveApiBase,
  resolveRewriteDestination,
} from './api-transport.ts';

const here = (file) => fileURLToPath(new URL(file, import.meta.url));

// --- proxy configuration ---------------------------------------------------

test('proxy mode uses the same-origin /api/v1 base', () => {
  const result = resolveApiBase({
    NEXT_PUBLIC_USE_API_PROXY: 'true',
    NEXT_PUBLIC_API_URL: 'http://internal-backend:8000/api/v1',
  });
  assert.deepEqual(result, { useProxy: true, apiBase: '/api/v1' });
});

test('an internal Docker URL is never emitted as the browser API base in proxy mode', () => {
  const { apiBase } = resolveApiBase({
    NEXT_PUBLIC_USE_API_PROXY: 'true',
    NEXT_PUBLIC_API_URL: 'http://backend:8000/api/v1',
    BACKEND_ORIGIN: 'http://backend:8000',
  });
  assert.equal(apiBase.includes('backend:8000'), false);
  assert.equal(apiBase, '/api/v1');
});

test('direct mode preserves the configured absolute API URL', () => {
  assert.deepEqual(
    resolveApiBase({
      NEXT_PUBLIC_USE_API_PROXY: 'false',
      NEXT_PUBLIC_API_URL: 'http://localhost:8000/api/v1',
    }),
    { useProxy: false, apiBase: 'http://localhost:8000/api/v1' },
  );
});

test('same-origin proxy mode is the safe default', () => {
  assert.deepEqual(resolveApiBase({}), {
    useProxy: true,
    apiBase: '/api/v1',
  });
});

test('only an explicit false opts into direct cross-origin mode', () => {
  assert.equal(
    resolveApiBase({ NEXT_PUBLIC_USE_API_PROXY: 'false' }).useProxy,
    false,
  );
  for (const value of ['true', 'TRUE', '1', 'yes', '', undefined]) {
    assert.equal(resolveApiBase({ NEXT_PUBLIC_USE_API_PROXY: value }).useProxy, true);
  }
});

test('backend origin normalization accepts bare origins and /api/v1 suffixes', () => {
  assert.equal(normalizeBackendOrigin('http://backend:8000'), 'http://backend:8000');
  assert.equal(normalizeBackendOrigin('http://backend:8000/'), 'http://backend:8000');
  assert.equal(
    normalizeBackendOrigin('https://api.example.com/api/v1'),
    'https://api.example.com',
  );
  assert.equal(normalizeBackendOrigin(undefined), '');
});

test('rewrite is installed only in proxy mode and forwards /api/v1', () => {
  assert.deepEqual(
    resolveRewriteDestination({
      NEXT_PUBLIC_USE_API_PROXY: 'false',
      BACKEND_ORIGIN: 'http://backend:8000',
    }),
    { useProxy: false, destination: null, error: null },
  );

  assert.deepEqual(
    resolveRewriteDestination({
      NEXT_PUBLIC_USE_API_PROXY: 'true',
      BACKEND_ORIGIN: 'http://backend:8000/api/v1',
    }),
    {
      useProxy: true,
      destination: 'http://backend:8000/api/v1/:path*',
      error: null,
    },
  );
});

test('production proxy mode without a server-side origin fails loudly', () => {
  const result = resolveRewriteDestination({
    NEXT_PUBLIC_USE_API_PROXY: 'true',
    NODE_ENV: 'production',
  });
  assert.equal(result.useProxy, true);
  assert.equal(result.destination, null);
  assert.match(result.error, /BACKEND_ORIGIN/);
});

test('browser base and rewrite always share the same proxy decision', () => {
  const snapshots = [
    { NODE_ENV: 'development' },
    { NEXT_PUBLIC_USE_API_PROXY: 'false', BACKEND_ORIGIN: 'http://backend:8000' },
    { NEXT_PUBLIC_USE_API_PROXY: 'true', BACKEND_ORIGIN: 'http://backend:8000' },
    { NEXT_PUBLIC_USE_API_PROXY: 'true', NEXT_PUBLIC_API_URL: 'http://backend:8000/api/v1' },
  ];
  for (const env of snapshots) {
    const base = resolveApiBase(env);
    const rewrite = resolveRewriteDestination(env);
    assert.equal(base.useProxy, rewrite.useProxy);
    if (base.useProxy) {
      assert.equal(base.apiBase, '/api/v1');
      assert.equal(rewrite.destination === null, rewrite.error !== null);
    }
  }
});

test('client transport source uses statically inlineable NEXT_PUBLIC references', () => {
  const source = readFileSync(here('./api-transport.ts'), 'utf8');
  assert.match(
    source,
    /NEXT_PUBLIC_USE_API_PROXY:\s*process\.env\.NEXT_PUBLIC_USE_API_PROXY/,
  );
  assert.match(
    source,
    /NEXT_PUBLIC_API_URL:\s*process\.env\.NEXT_PUBLIC_API_URL/,
  );
});

// --- error classification --------------------------------------------------

test('HTTP responses keep the backend detail', () => {
  const httpError = {
    isAxiosError: true,
    response: { status: 422, data: { detail: 'Approved models must be valid.' } },
    message: 'Request failed with status code 422',
  };
  assert.equal(isApiTransportError(httpError), false);
  assert.equal(apiErrorMessage(httpError), 'Approved models must be valid.');
});

test('HTTP responses with structured detail keep the message', () => {
  const err = {
    isAxiosError: true,
    response: { status: 409, data: { detail: { message: 'Policy changed; reload.' } } },
    message: 'Request failed with status code 409',
  };
  assert.equal(apiErrorMessage(err), 'Policy changed; reload.');
});

test('HTTP responses without detail still report the status', () => {
  const err = { isAxiosError: true, response: { status: 503, data: {} } };
  assert.match(apiErrorMessage(err), /HTTP 503/);
});

test('a missing response is an actionable transport failure, not a validation error', () => {
  const networkError = {
    isAxiosError: true,
    code: 'ERR_NETWORK',
    message: 'Network Error',
  };
  assert.equal(isApiTransportError(networkError), true);
  const message = apiErrorMessage(networkError, '/api/v1');
  assert.match(message, /Could not reach the backend \(\/api\/v1\)/);
  assert.match(message, /running and reachable/);
  assert.equal(/validation|invalid policy/i.test(message), false);
});

test('a timed-out request is also a transport failure', () => {
  const err = { isAxiosError: true, code: 'ECONNABORTED', message: 'timeout' };
  assert.equal(isApiTransportError(err), true);
  assert.match(apiErrorMessage(err), /Could not reach the backend/);
});

test('generic errors and empty values fall back safely', () => {
  assert.equal(apiErrorMessage(new Error('boom')), 'boom');
  assert.equal(apiErrorMessage(null), 'Something went wrong. Please try again.');
  assert.equal(isApiTransportError({ response: { status: 500 } }), false);
  assert.equal(isApiTransportError('Network Error'), false);
});

// --- policy-save source contracts -----------------------------------------

test('policy save calls the admin PUT endpoint with the policy payload', () => {
  const apiSource = readFileSync(here('./api.ts'), 'utf8');
  assert.match(
    apiSource,
    /updateKllmAutoload[\s\S]{0,160}?\.put<KllmAutoloadPolicy>\('\/admin\/kllm\/autoload', data\)/,
  );
});

test('a successful PUT is not reported failed when the refresh fails', () => {
  const pageSource = readFileSync(
    new URL('../app/admin/(console)/kllm/page.tsx', import.meta.url),
    'utf8',
  );
  assert.match(pageSource, /adminApi\.updateKllmAutoload\(next\)/);
  assert.match(pageSource, /isApiTransportError\(err\)/);
  assert.match(pageSource, /Cannot reach the backend/);
  assert.match(pageSource, /await invalidate\(\)[\s\S]{0,120}?catch/);
});
