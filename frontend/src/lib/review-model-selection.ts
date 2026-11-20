import type { ReviewSelection } from '@/lib/api';

export interface ModelSelectionView {
  /** Lowercase provider identifier used by ProviderIcon. */
  providerSlug: string | null;
  /** Human-readable provider label. */
  providerLabel: string;
  /** Selected model identifier (never a fabricated default). */
  model: string | null;
  /** True when both provider and model were resolved. */
  hasSelection: boolean;
  mappingLabel: string;
  sourceLabel: string;
  actualProvider: string | null;
  actualModel: string | null;
  actualLabel: string;
  executed: boolean;
  fallbackUsed: boolean;
  fallbackReason: string | null;
}

const SOURCE_LABELS: Record<string, string> = {
  repository_mapping: 'Repository Mapping',
  routing_fallback: 'Global Routing',
  unresolved: 'Not configured',
  unknown: 'Source not recorded',
};

const MAPPING_LABELS: Record<string, string> = {
  mapped: 'Mapped',
  not_mapped: 'Not mapped',
  unknown: 'Unknown',
};

/**
 * Provider display-name normalization for review metadata.
 *
 * The managed provider's internal slug is always `kllm`, but the visible name
 * is standardized to `kLLM` everywhere review runs are displayed (live or
 * stored), regardless of any legacy parenthetical suffix a backend row may
 * carry. The internal slug remains `kllm` for routing and persistence.
 */
export function normalizeKllmProviderLabel(
  slug?: string | null,
  name?: string | null,
): string | null {
  const normalizedSlug = (slug ?? '').trim().toLowerCase();
  const normalizedName = (name ?? '').trim();
  if (
    normalizedSlug === 'kllm' ||
    normalizedName.toLowerCase() === 'kllm' ||
    normalizedName.toLowerCase().startsWith('kllm')
  ) {
    return 'kLLM';
  }
  return null;
}

function displayProviderLabel(
  slug?: string | null,
  name?: string | null,
  fallback = '',
): string {
  return normalizeKllmProviderLabel(slug, name) ?? (name || slug || fallback);
}

export type ModelSelectionInput = {
  [K in keyof ReviewSelection]?: ReviewSelection[K] | null;
};

/**
 * Single source of truth for provider/model display across review cards,
 * review details and admin tables. Never substitutes a provider or model that
 * was not actually selected/executed.
 */
export function modelSelectionView(
  selection: ModelSelectionInput | null | undefined,
): ModelSelectionView {
  const providerSlug = (
    selection?.selected_provider_slug ??
    selection?.selected_provider ??
    null
  )?.toLowerCase() ?? null;
  const providerLabel =
    displayProviderLabel(
      providerSlug,
      selection?.selected_provider_name,
      selection?.selected_provider ?? selection?.selected_provider_slug ?? '',
    ) || 'AI model';
  const model = selection?.selected_model ?? null;
  const hasSelection = Boolean(providerSlug && model);

  const actualProvider =
    selection?.actual_execution_provider ||
    null;
  const actualModel = selection?.actual_execution_model || null;
  const executed = Boolean(
    selection?.execution_started && (actualProvider || actualModel),
  );
  const executionStatus = selection?.execution_status || null;
  const fallbackUsed = Boolean(selection?.fallback_used);

  let actualLabel: string;
  if (executed) {
    actualLabel = [
      displayProviderLabel(actualProvider),
      actualModel,
    ]
      .filter(Boolean)
      .join(' · ');
  } else if (executionStatus === 'running') {
    actualLabel = 'Running · not recorded yet';
  } else if (executionStatus === 'queued' || executionStatus === 'pending') {
    actualLabel = 'Queued · not executed yet';
  } else if (executionStatus === 'cancelled') {
    actualLabel = 'Cancelled before execution';
  } else if (executionStatus === 'failed') {
    actualLabel = 'Failed · actual not recorded';
  } else {
    actualLabel = 'Not executed';
  }

  return {
    providerSlug,
    providerLabel,
    model,
    hasSelection,
    mappingLabel:
      MAPPING_LABELS[selection?.repository_mapping_status ?? 'unknown'] ??
      'Unknown',
    sourceLabel:
      SOURCE_LABELS[selection?.selection_source ?? 'unknown'] ??
      'Source not recorded',
    actualProvider,
    actualModel,
    actualLabel,
    executed,
    fallbackUsed,
    fallbackReason: selection?.fallback_reason ?? null,
  };
}
