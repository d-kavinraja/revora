import type { PillTone } from '@/components/shared/pill';

export const FEATURE_META: Record<string, { label: string; description: string }> = {
  model_lab: {
    label: 'Model Lab',
    description:
      'Model Lab page and the free-model execution route (GET /models, POST /llm/execute).',
  },
  mouthmap: {
    label: 'MouthMap',
    description: 'MouthMap video inference lab and all of its processing routes.',
  },
  botaniq: {
    label: 'BotaniQ',
    description: 'BotaniQ plant-disease inference lab and all of its processing routes.',
  },
  api_keys_add: {
    label: 'API Key Changes',
    description:
      'Creating, updating and rotating API keys. Viewing, testing and deleting keys stays available.',
  },
  routing_mapping: {
    label: 'Routing Mapping',
    description:
      'Saving feature to provider/model routing preferences. The current mapping stays visible.',
  },
  review_initiation: {
    label: 'Review Initiation',
    description:
      'Rerun, retry and restart of reviews. Cancelling an in-flight review stays allowed.',
  },
  reviews: {
    label: 'Reviews',
    description:
      'Reviews page and review read APIs. Background webhook processing, queueing and execution continue when disabled.',
  },
  usage: {
    label: 'Usage',
    description: 'Usage dashboards and their data endpoints.',
  },
  analytics: {
    label: 'Analytics',
    description: 'Analytics dashboards and their data endpoints.',
  },
  guide: {
    label: 'Setup Guide',
    description: 'The onboarding setup guide page.',
  },
};

export const FEATURE_STATUS_OPTIONS = [
  'enabled',
  'disabled',
  'maintenance',
  'coming_soon',
  'under_testing',
] as const;

export const FEATURE_STATUS_LABELS: Record<string, string> = {
  enabled: 'Enabled',
  disabled: 'Disabled',
  maintenance: 'Maintenance',
  coming_soon: 'Coming soon',
  under_testing: 'Under testing',
};

export const FEATURE_STATUS_TONES: Record<string, PillTone> = {
  enabled: 'success',
  disabled: 'muted',
  maintenance: 'warning',
  coming_soon: 'info',
  under_testing: 'warning',
};

export function featureLabel(key: string): string {
  return FEATURE_META[key]?.label ?? key;
}

export function featureStatusLabel(status: string): string {
  return FEATURE_STATUS_LABELS[status] ?? status;
}
