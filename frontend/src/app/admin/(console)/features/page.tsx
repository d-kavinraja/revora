'use client';

import { useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Flag } from 'lucide-react';
import { adminApi, type AdminFeatureFlag } from '@/lib/api';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Pill, type PillTone } from '@/components/shared/pill';
import { useToast } from '@/components/ui/toaster';

const FLAG_META: Record<string, { label: string; description: string }> = {
  model_lab: {
    label: 'Model Lab',
    description:
      'Model Lab page and the free-model execution route (GET /models, POST /llm/execute).',
  },
  mouthmap: {
    label: 'MouthMap',
    description: 'MouthMap video inference lab and all of its processing routes.',
  },
  api_keys_add: {
    label: 'API Key Changes',
    description:
      'Creating, updating and rotating API keys. Viewing, testing and deleting keys stays available.',
  },
  routing_mapping: {
    label: 'Routing Mapping',
    description:
      'Saving feature → provider/model routing preferences (current mapping stays visible).',
  },
  review_initiation: {
    label: 'Review Initiation',
    description:
      'Rerun / retry / restart of reviews. Cancelling an in-flight review stays allowed.',
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

const STATUS_OPTIONS = [
  'enabled',
  'disabled',
  'maintenance',
  'coming_soon',
  'under_testing',
];

const STATUS_LABELS: Record<string, string> = {
  enabled: 'Enabled',
  disabled: 'Disabled',
  maintenance: 'Maintenance',
  coming_soon: 'Coming soon',
  under_testing: 'Under testing',
};

const STATUS_TONES: Record<string, PillTone> = {
  enabled: 'success',
  disabled: 'muted',
  maintenance: 'warning',
  coming_soon: 'info',
  under_testing: 'warning',
};

interface Draft {
  status: string;
  message: string;
}

function errorDetail(error: unknown): string | null {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return null;
}

const selectCls =
  'h-11 rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';
const inputCls =
  'w-full h-11 rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

export default function AdminFeaturesPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [confirmingKey, setConfirmingKey] = useState<string | null>(null);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'features'],
    queryFn: adminApi.features,
    retry: 1,
  });

  const flagByKey = new Map((data ?? []).map((flag) => [flag.key, flag]));

  const updateMutation = useMutation({
    mutationFn: (input: { key: string; status: string; message: string | null }) =>
      adminApi.updateFeature(input.key, {
        status: input.status,
        message: input.message,
      }),
    onSuccess: (flag) => {
      toast({
        title: `${FLAG_META[flag.key]?.label ?? flag.key} is now ${STATUS_LABELS[flag.status] ?? flag.status}`,
        description: 'The change is live and has been audited.',
        type: 'success',
      });
      setDrafts((prev) => {
        const next = { ...prev };
        delete next[flag.key];
        return next;
      });
      setConfirmingKey(null);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'features'] });
      void queryClient.invalidateQueries({ queryKey: ['platform-features'] });
      void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
    },
    onError: (error) => {
      toast({
        title: 'Could not update feature flag',
        description: errorDetail(error) ?? undefined,
        type: 'error',
      });
      setConfirmingKey(null);
    },
  });

  const draftFor = (flag: AdminFeatureFlag): Draft =>
    drafts[flag.key] ?? { status: flag.status, message: flag.message ?? '' };

  const setDraft = (flag: AdminFeatureFlag, patch: Partial<Draft>) => {
    setDrafts((prev) => ({
      ...prev,
      [flag.key]: { ...draftFor(flag), ...patch },
    }));
  };

  const isDirty = (flag: AdminFeatureFlag): boolean => {
    const draft = drafts[flag.key];
    if (!draft) return false;
    return (
      draft.status !== flag.status ||
      draft.message.trim() !== (flag.message ?? '')
    );
  };

  const confirmingFlag = confirmingKey ? flagByKey.get(confirmingKey) : null;
  const confirmingDraft =
    confirmingFlag && confirmingKey ? draftFor(confirmingFlag) : null;

  return (
    <div>
      <div>
        <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
          Features
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Platform feature flags. Disabling a flag makes every non-admin request
          for that feature answer 503 with the message below, and hides it from
          navigation — no redeploy, nothing deleted. Admins always bypass
          flags; re-enabling restores the feature instantly with all stored
          data intact.
        </p>
      </div>

      {isError && !isPending && (
        <div
          role="alert"
          className="mt-4 flex items-center gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error"
        >
          <AlertTriangle size={18} className="shrink-0" />
          <span>
            Could not load feature flags.{' '}
            <button
              type="button"
              onClick={() => refetch()}
              className="underline underline-offset-2 cursor-pointer"
            >
              Try again
            </button>
          </span>
        </div>
      )}

      {isPending && !isError && (
        <div className="mt-4 rounded-xl border border-border bg-surface-1 p-8 text-center text-sm text-muted-foreground">
          Loading feature flags…
        </div>
      )}

      <div className="mt-4 space-y-4">
        {(data ?? []).map((flag) => {
          const meta = FLAG_META[flag.key] ?? {
            label: flag.key,
            description: 'Platform feature flag.',
          };
          const draft = draftFor(flag);
          const dirty = isDirty(flag);
          const busy =
            updateMutation.isPending && confirmingKey === flag.key;
          return (
            <div
              key={flag.key}
              className="rounded-xl border border-border bg-surface-1 p-5"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex items-start gap-3 min-w-0">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2">
                    <Flag size={16} />
                  </span>
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-foreground">
                      {meta.label}
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      {meta.description}
                    </p>
                    <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                      {flag.key}
                    </p>
                  </div>
                </div>
                <Pill tone={STATUS_TONES[flag.status] ?? 'muted'}>
                  {STATUS_LABELS[flag.status] ?? flag.status}
                </Pill>
              </div>

              <div className="mt-4 grid gap-3 lg:grid-cols-[200px_minmax(0,1fr)_auto] lg:items-end">
                <div>
                  <label
                    htmlFor={`status-${flag.key}`}
                    className="mb-1 block text-xs font-medium text-muted-foreground"
                  >
                    Status
                  </label>
                  <select
                    id={`status-${flag.key}`}
                    value={draft.status}
                    onChange={(event) =>
                      setDraft(flag, { status: event.target.value })
                    }
                    className={`${selectCls} w-full`}
                  >
                    {STATUS_OPTIONS.map((status) => (
                      <option key={status} value={status}>
                        {STATUS_LABELS[status]}
                      </option>
                    ))}
                  </select>
                </div>
                <div className="min-w-0">
                  <label
                    htmlFor={`message-${flag.key}`}
                    className="mb-1 block text-xs font-medium text-muted-foreground"
                  >
                    User-facing message (optional — shown with the 503)
                  </label>
                  <input
                    id={`message-${flag.key}`}
                    type="text"
                    value={draft.message}
                    maxLength={300}
                    placeholder={
                      flag.key === 'model_lab'
                        ? 'Model Lab is temporarily unavailable while we update the service.'
                        : 'This feature is temporarily unavailable. Please try again later.'
                    }
                    onChange={(event) =>
                      setDraft(flag, { message: event.target.value })
                    }
                    className={inputCls}
                  />
                </div>
                <button
                  type="button"
                  disabled={!dirty || updateMutation.isPending}
                  onClick={() => setConfirmingKey(flag.key)}
                  className="inline-flex h-11 items-center justify-center rounded-lg border border-border bg-surface-2 px-4 text-sm font-medium text-foreground transition-colors hover:bg-surface-1 disabled:cursor-not-allowed disabled:opacity-50 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
                >
                  {busy ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      <ConfirmDialog
        open={confirmingFlag !== null}
        title={
          confirmingFlag && confirmingDraft
            ? `Update ${FLAG_META[confirmingFlag.key]?.label ?? confirmingFlag.key}`
            : 'Update feature flag'
        }
        description={
          confirmingFlag && confirmingDraft
            ? confirmingDraft.status === 'enabled'
              ? 'The feature becomes available to non-admin users immediately — no redeploy, no re-login needed.'
              : confirmingDraft.status === 'maintenance'
                ? 'Non-admin users will receive 503 with a maintenance message. Nothing is deleted; re-enabling restores the feature instantly.'
                : 'Non-admin users will receive 503 for this feature and it disappears from their navigation. Nothing is deleted; re-enabling restores it instantly.'
            : undefined
        }
        confirmLabel="Apply"
        busy={updateMutation.isPending}
        onConfirm={() => {
          if (!confirmingFlag || !confirmingDraft) return;
          updateMutation.mutate({
            key: confirmingFlag.key,
            status: confirmingDraft.status,
            message: confirmingDraft.message.trim() || null,
          });
        }}
        onCancel={() => {
          if (!updateMutation.isPending) setConfirmingKey(null);
        }}
      >
        <p className="text-sm text-muted-foreground">
          Effective immediately for all users and written to the audit log.
          Admins always bypass flags.
        </p>
      </ConfirmDialog>
    </div>
  );
}
