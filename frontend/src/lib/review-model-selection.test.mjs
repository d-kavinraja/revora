import assert from 'node:assert/strict';
import test from 'node:test';

import { modelSelectionView } from './review-model-selection.ts';

const baseSelection = {
  repository_mapping_status: 'mapped',
  repository_provider: 'kllm',
  repository_model: 'qwen3.8-27b',
  selection_source: 'repository_mapping',
  selected_provider: 'kllm',
  selected_provider_slug: 'kllm',
  selected_provider_name: 'kLLM',
  selected_model: 'qwen3.8-27b',
  actual_execution_provider: null,
  actual_execution_model: null,
  execution_status: 'running',
  execution_started: true,
  fallback_used: false,
  fallback_reason: null,
};

test('primary mapped model: no fallback, mappedVsExecutingDiffer false', () => {
  const view = modelSelectionView(baseSelection);
  assert.equal(view.fallbackUsed, false);
  assert.equal(view.mappedVsExecutingDiffer, false);
  assert.equal(view.hasSelection, true);
  assert.equal(view.providerLabel, 'kLLM');
  assert.equal(view.model, 'qwen3.8-27b');
  assert.equal(view.isExecuting, true);
  assert.equal(view.actualLabel, 'kLLM · qwen3.8-27b');
});

test('fallback selected: mappedVsExecutingDiffer true, fallbackUsed true', () => {
  const view = modelSelectionView({
    ...baseSelection,
    selected_provider: 'gemini',
    selected_provider_slug: 'gemini',
    selected_provider_name: 'Gemini',
    selected_model: 'gemini-2.5-flash',
    fallback_used: true,
    fallback_reason: 'primary_unavailable',
  });
  assert.equal(view.fallbackUsed, true);
  assert.equal(view.mappedVsExecutingDiffer, true);
  assert.equal(view.hasSelection, true);
  assert.equal(view.providerLabel, 'Gemini');
  assert.equal(view.model, 'gemini-2.5-flash');
  assert.equal(view.fallbackReason, 'primary_unavailable');
  assert.equal(view.actualLabel, 'Gemini · gemini-2.5-flash');
});

test('fallback not displayed before selection is resolved', () => {
  const view = modelSelectionView(null);
  assert.equal(view.hasSelection, false);
  assert.equal(view.fallbackUsed, false);
  assert.equal(view.mappedVsExecutingDiffer, false);
  assert.equal(view.actualLabel, 'Not executed');
});

test('not resolved shows Model not resolved label', () => {
  const view = modelSelectionView({
    repository_mapping_status: 'not_mapped',
    repository_provider: null,
    repository_model: null,
    selection_source: 'unresolved',
    selected_provider: null,
    selected_provider_slug: null,
    selected_provider_name: null,
    selected_model: null,
    actual_execution_provider: null,
    actual_execution_model: null,
    execution_status: 'pending',
    execution_started: false,
    fallback_used: false,
  });
  assert.equal(view.hasSelection, false);
  assert.equal(view.mappedVsExecutingDiffer, false);
  assert.equal(view.fallbackUsed, false);
  assert.equal(view.actualLabel, 'Queued · not executed yet');
});

test('completed execution shows actual provider/model', () => {
  const view = modelSelectionView({
    ...baseSelection,
    execution_status: 'completed',
    execution_started: true,
    actual_execution_provider: 'gemini',
    actual_execution_model: 'gemini-2.5-flash',
    selected_provider: 'gemini',
    selected_model: 'gemini-2.5-flash',
    fallback_used: true,
  });
  assert.equal(view.executed, true);
  assert.equal(view.isExecuting, false);
  assert.equal(view.actualLabel, 'gemini · gemini-2.5-flash');
  assert.equal(view.fallbackUsed, true);
});

test('running with resolved selection does not show "Running · not recorded yet"', () => {
  const view = modelSelectionView({
    ...baseSelection,
    selected_provider: 'gemini',
    selected_provider_slug: 'gemini',
    selected_provider_name: 'Gemini',
    selected_model: 'gemini-2.5-flash',
    fallback_used: true,
  });
  assert.equal(view.isExecuting, true);
  assert.equal(view.actualLabel, 'Gemini · gemini-2.5-flash');
  assert.notEqual(view.actualLabel, 'Running · not recorded yet');
});

test('repository mapping unchanged when fallback active', () => {
  const view = modelSelectionView({
    ...baseSelection,
    selected_provider: 'gemini',
    selected_provider_slug: 'gemini',
    selected_provider_name: 'Gemini',
    selected_model: 'gemini-2.5-flash',
    fallback_used: true,
  });
  assert.equal(view.mappedVsExecutingDiffer, true);
  assert.equal(view.repositoryProvider, 'kllm');
  assert.equal(view.repositoryModel, 'qwen3.8-27b');
  assert.equal(view.mappingLabel, 'Mapped');
});
