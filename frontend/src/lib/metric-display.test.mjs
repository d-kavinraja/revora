import assert from 'node:assert/strict';
import test from 'node:test';

import { metricDisplay } from './metric-display.ts';

test('passes genuine numbers through, including zero', () => {
  assert.equal(metricDisplay(0), 0);
  assert.equal(metricDisplay(1), 1);
  assert.equal(metricDisplay(12345), 12345);
});

test('renders unknown values as an em dash, never as zero', () => {
  assert.equal(metricDisplay(undefined), '—');
  assert.equal(metricDisplay(null), '—');
  assert.equal(metricDisplay(Number.NaN), '—');
  assert.equal(metricDisplay(Number.POSITIVE_INFINITY), '—');
});

test('an unknown value is never reported as a numeric zero', () => {
  const displayed = metricDisplay(undefined);
  assert.notEqual(displayed, 0);
  assert.equal(typeof displayed === 'number', false);
});