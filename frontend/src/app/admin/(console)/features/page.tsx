'use client';

import { useMemo, useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { BarChart3, Flag } from 'lucide-react';
import { adminApi, type AdminFeatureFlag, type AdminUsageAnalytics } from '@/lib/api';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Pill } from '@/components/shared/pill';
import { TextFilter } from '@/components/shared/text-filter';
import { formatDateTime } from '@/components/shared/time-ago';
import { useToast } from '@/components/ui/toaster';
import { AdminPage } from '@/components/admin/page-shell';
import {
  AdminButton,
  AdminSwitch,
  ADMIN_INPUT_CLASS,
  Field,
  FilterBar,
  SelectFilter,
} from '@/components/admin/controls';
import { AdminLoading, InlineEmpty, QueryError } from '@/components/admin/states';
import {
  FEATURE_META,
  FEATURE_STATUS_LABELS,
  FEATURE_STATUS_OPTIONS,
  FEATURE_STATUS_TONES,
  featureLabel,
} from '@/lib/admin-features';

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

export default function AdminFeaturesPage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [confirmingKey, setConfirmingKey] = useState<string | null>(null);
  const [analyticsDraft, setAnalyticsDraft] = useState<boolean | null>(null);
  const [confirmingAnalytics, setConfirmingAnalytics] = useState(false);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'features'],
    queryFn: adminApi.features,
    retry: 1,
  });

  const {
    data: analyticsState,
    isPending: analyticsPending,
    isError: analyticsError,
    refetch: refetchAnalytics,
  } = useQuery({
    queryKey: ['admin', 'usage-analytics'],
    queryFn: adminApi.usageAnalytics,
    retry: 1,
  });

  const analyticsMutation = useMutation({
    mutationFn: (input: { enabled: boolean; version: number }) =>
      adminApi.updateUsageAnalytics({
        enabled: input.enabled,
        version: input.version,
      }),
    onSuccess: (state: AdminUsageAnalytics) => {
      toast({
        title: state.enabled ? 'Usage analytics enabled' : 'Usage analytics disabled',
        description: 'The change is live and has been audited.',
        type: 'success',
      });
      setAnalyticsDraft(null);
      setConfirmingAnalytics(false);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'usage-analytics'] });
      void queryClient.invalidateQueries({ queryKey: ['platform-features'] });
      void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
    },
    onError: (error) => {
      toast({
        title: 'Could not update usage analytics',
        description: errorDetail(error) ?? undefined,
        type: 'error',
      });
      setConfirmingAnalytics(false);
    },
  });

  const flagByKey = new Map((data ?? []).map((flag) => [flag.key, flag]));

  const filteredFlags = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (data ?? []).filter((flag) => {
      const meta = FEATURE_META[flag.key];
      const matchesQuery =
        !query ||
        featureLabel(flag.key).toLowerCase().includes(query) ||
        flag.key.toLowerCase().includes(query) ||
        (meta?.description ?? '').toLowerCase().includes(query);
      const matchesStatus = !statusFilter || flag.status === statusFilter;
      return matchesQuery && matchesStatus;
    });
  }, [data, search, statusFilter]);

  const updateMutation = useMutation({
    mutationFn: (input: { key: string; status: string; message: string | null }) =>
      adminApi.updateFeature(input.key, {
        status: input.status,
        message: input.message,
      }),
    onSuccess: (flag) => {
      toast({
        title: `${featureLabel(flag.key)} is now ${FEATURE_STATUS_LABELS[flag.status] ?? flag.status}`,
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
    <AdminPage
      eyebrow="System"
      title="Features"
      description="Turn user-facing features on or off without a redeploy. Admins always bypass flags; changes apply immediately and are written to the audit log."
    >
      {isError && !isPending && (
        <QueryError
          message="Could not load feature flags."
          onRetry={() => refetch()}
        />
      )}

      {isPending && !isError && <AdminLoading label="Loading feature flags…" />}

      {analyticsError && !analyticsPending && (
        <QueryError message="Could not load usage analytics state." onRetry={() => refetchAnalytics()} />
      )}

      {analyticsPending && !analyticsError && <AdminLoading label="Loading usage analytics…" />}

      {analyticsState && (
        <section className="rounded-xl border border-border bg-surface-1 p-5">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="flex min-w-0 items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2">
                <BarChart3 size={16} aria-hidden="true" />
              </span>
              <div className="min-w-0">
                <h2 className="text-sm font-semibold text-foreground">Usage & Analytics</h2>
                <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                  Master switch for optional usage tracking and analytics collection across Revora. Disabling pauses new
                  optional analytics events while preserving historical data; the Usage and Analytics page-access flags below
                  remain independent.
                </p>
                <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                  usage_analytics
                </p>
              </div>
            </div>
            <Pill tone={analyticsState.enabled ? 'success' : 'muted'} dot>
              {analyticsState.enabled ? 'Enabled' : 'Disabled'}
            </Pill>
          </div>

          <div className="mt-3 text-xs text-muted-foreground">
            {analyticsState.changed_at
              ? `Changed ${formatDateTime(analyticsState.changed_at)}`
              : 'Never changed'}
            {' · v'}
            {analyticsState.version}
            {analyticsState.changed_at && (
              <span className="ml-2 font-mono text-[11px]">by {analyticsState.changed_by ?? 'system'}</span>
            )}
          </div>

          <div className="mt-4">
            <AdminSwitch
              checked={analyticsDraft ?? analyticsState.enabled}
              onChange={(next) => setAnalyticsDraft(next)}
              title="Collect usage analytics"
              description="Disabling pauses new optional analytics events while keeping historical data. The Usage and Analytics page-access flags below remain independent."
            />
          </div>

          <div className="mt-4">
            <AdminButton
              variant="secondary"
              disabled={
                analyticsDraft === null ||
                analyticsDraft === analyticsState.enabled ||
                analyticsMutation.isPending
              }
              onClick={() => setConfirmingAnalytics(true)}
            >
              {analyticsMutation.isPending ? 'Saving…' : 'Save'}
            </AdminButton>
          </div>
        </section>
      )}

      <details className="group rounded-xl border border-border bg-surface-1 p-5 open:pb-5">
        <summary className="cursor-pointer list-none text-sm font-medium text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand">
          How feature flags affect users
          <span className="ml-2 text-xs font-normal text-muted-foreground group-open:hidden">
            Show
          </span>
        </summary>
        <p className="mt-3 max-w-[75ch] text-sm leading-relaxed text-muted-foreground">
          Disabling a flag returns 503 for non-admin requests with the message
          below. The feature stays in navigation so users see a clear
          unavailable state. Nothing is deleted, and re-enabling restores it
          instantly. Maintenance, coming soon and under testing are separate
          availability states for planned work.
        </p>
      </details>

      <FilterBar
        label="Feature flag filters"
        actions={
          <span className="text-xs text-muted-foreground">
            {filteredFlags.length} of {data?.length ?? 0} flags
          </span>
        }
      >
        <TextFilter
          value={search}
          onChange={setSearch}
          placeholder="Search flags…"
          ariaLabel="Search feature flags"
          className="w-full sm:w-64"
        />
        <SelectFilter
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          aria-label="Filter by status"
          className="w-full sm:w-48"
        >
          <option value="">All statuses</option>
          {FEATURE_STATUS_OPTIONS.map((status) => (
            <option key={status} value={status}>
              {FEATURE_STATUS_LABELS[status]}
            </option>
          ))}
        </SelectFilter>
      </FilterBar>

      <div className="space-y-4">
        {filteredFlags.length === 0 ? (
          <InlineEmpty>No feature flags match the current filters.</InlineEmpty>
        ) : filteredFlags.map((flag) => {
          const meta = FEATURE_META[flag.key] ?? {
            label: flag.key,
            description: 'Platform feature flag.',
          };
          const draft = draftFor(flag);
          const dirty = isDirty(flag);
          const busy =
            updateMutation.isPending && confirmingKey === flag.key;
          return (
            <section
              key={flag.key}
              className="rounded-xl border border-border bg-surface-1 p-5"
            >
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2">
                    <Flag size={16} aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <h2 className="text-sm font-semibold text-foreground">
                      {meta.label}
                    </h2>
                    <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                      {meta.description}
                    </p>
                    <p className="mt-1 font-mono text-[11px] text-muted-foreground">
                      {flag.key}
                    </p>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  {dirty && (
                    <Pill tone="warning" dot>
                      Unsaved
                    </Pill>
                  )}
                  <Pill
                    tone={FEATURE_STATUS_TONES[flag.status] ?? 'muted'}
                    dot
                  >
                    {FEATURE_STATUS_LABELS[flag.status] ?? flag.status}
                  </Pill>
                </div>
              </div>

              <div className="mt-4 rounded-lg border border-border bg-surface-2/40 p-3">
                <AdminSwitch
                  checked={draft.status === 'enabled'}
                  onChange={(next) =>
                    setDraft(flag, {
                      status: next ? 'enabled' : 'disabled',
                    })
                  }
                  disabled={updateMutation.isPending}
                  title="Enabled for users"
                  description="On sets Enabled; off sets Disabled. Use Status below for maintenance, coming soon or under testing."
                />
              </div>

              <div className="mt-3 grid gap-3 lg:grid-cols-[200px_minmax(0,1fr)_auto] lg:items-end">
                <Field label="Status" htmlFor={`status-${flag.key}`}>
                  <SelectFilter
                    id={`status-${flag.key}`}
                    value={draft.status}
                    onChange={(event) =>
                      setDraft(flag, { status: event.target.value })
                    }
                    className="w-full"
                  >
                    {FEATURE_STATUS_OPTIONS.map((status) => (
                      <option key={status} value={status}>
                        {FEATURE_STATUS_LABELS[status]}
                      </option>
                    ))}
                  </SelectFilter>
                </Field>
                <Field
                  label="User-facing message (optional, shown with the 503)"
                  htmlFor={`message-${flag.key}`}
                >
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
                    className={ADMIN_INPUT_CLASS}
                  />
                </Field>
                <AdminButton
                  variant={dirty ? 'primary' : 'secondary'}
                  disabled={!dirty || updateMutation.isPending}
                  onClick={() => setConfirmingKey(flag.key)}
                  className="w-full lg:w-auto"
                >
                  {busy ? 'Saving…' : 'Save'}
                </AdminButton>
              </div>
            </section>
          );
        })}
      </div>

      <ConfirmDialog
        open={confirmingFlag !== null}
        title={
          confirmingFlag && confirmingDraft
            ? `Update ${featureLabel(confirmingFlag.key)}`
            : 'Update feature flag'
        }
        description={
          confirmingFlag && confirmingDraft
            ? confirmingDraft.status === 'enabled'
              ? 'The feature becomes available to non-admin users immediately — no redeploy, no re-login needed.'
              : confirmingDraft.status === 'maintenance'
                ? 'Non-admin users will receive 503 with a maintenance message. Nothing is deleted; re-enabling restores the feature instantly.'
                : 'Non-admin users will receive 503 for this feature and see a clear unavailable page while its navigation item stays visible. Nothing is deleted; re-enabling restores it instantly.'
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

      <ConfirmDialog
        open={confirmingAnalytics}
        title={
          (analyticsDraft ?? analyticsState?.enabled)
            ? 'Enable usage analytics'
            : 'Disable usage analytics'
        }
        description={
          analyticsDraft
            ? 'Optional analytics collection and dashboards resume immediately.'
            : 'New optional analytics collection pauses. Historical data is preserved and core functionality continues.'
        }
        confirmLabel={analyticsDraft ? 'Enable' : 'Disable'}
        busy={analyticsMutation.isPending}
        onConfirm={() => {
          if (!analyticsState || analyticsDraft === null) return;
          analyticsMutation.mutate({
            enabled: analyticsDraft,
            version: analyticsState.version,
          });
        }}
        onCancel={() => {
          if (!analyticsMutation.isPending) setConfirmingAnalytics(false);
        }}
      >
        <p className="text-sm text-muted-foreground">
          The change is applied immediately and written to the audit log.
        </p>
      </ConfirmDialog>
    </AdminPage>
  );
}
