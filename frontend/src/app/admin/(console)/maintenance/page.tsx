'use client';

import { useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Wrench } from 'lucide-react';
import {
  adminApi,
  type AdminMaintenanceFull,
  type AdminMaintenanceUpdate,
} from '@/lib/api';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Pill } from '@/components/shared/pill';
import { useToast } from '@/components/ui/toaster';
import { formatDateTime } from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import {
  AdminButton,
  ADMIN_INPUT_CLASS,
  ADMIN_TEXTAREA_CLASS,
  CheckboxRow,
  Field,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

interface MaintenanceForm {
  enabled: boolean;
  title: string;
  message: string;
  eta: string;
  reason: string;
}

function toDatetimeLocal(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(
    date.getDate()
  )}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function fromForm(data: AdminMaintenanceFull): MaintenanceForm {
  return {
    enabled: data.enabled,
    title: data.title ?? '',
    message: data.message ?? '',
    eta: toDatetimeLocal(data.expected_return_at),
    reason: data.reason ?? '',
  };
}

function buildPayload(
  data: AdminMaintenanceFull,
  form: MaintenanceForm
): AdminMaintenanceUpdate {
  const payload: AdminMaintenanceUpdate = { version: data.version };
  if (form.enabled !== data.enabled) payload.enabled = form.enabled;
  if (form.title.trim() !== (data.title ?? '')) {
    payload.title = form.title.trim() || null;
  }
  if (form.message.trim() !== (data.message ?? '')) {
    payload.message = form.message.trim() || null;
  }
  if (form.eta !== toDatetimeLocal(data.expected_return_at)) {
    payload.expected_return_at = form.eta
      ? new Date(form.eta).toISOString()
      : null;
  }
  if (form.reason.trim() !== (data.reason ?? '')) {
    payload.reason = form.reason.trim() || null;
  }
  return payload;
}

function errorInfo(error: unknown): { title: string; description?: string } {
  if (axios.isAxiosError(error)) {
    if (error.response?.status === 409) {
      return {
        title: 'State changed elsewhere',
        description:
          'Maintenance state changed since this page loaded. Reload and retry.',
      };
    }
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') {
      return { title: 'Could not update maintenance mode', description: detail };
    }
  }
  return { title: 'Could not update maintenance mode' };
}

export default function AdminMaintenancePage() {
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const [form, setForm] = useState<MaintenanceForm | null>(null);
  const [confirming, setConfirming] = useState(false);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'maintenance'],
    queryFn: adminApi.maintenance,
    retry: 1,
  });

  const current = form ?? (data ? fromForm(data) : null);

  const updateMutation = useMutation({
    mutationFn: (payload: AdminMaintenanceUpdate) =>
      adminApi.updateMaintenance(payload),
    onSuccess: (state) => {
      toast({
        title: state.enabled
          ? 'Maintenance mode enabled'
          : 'Maintenance mode disabled',
        description: 'The change is live and has been audited.',
        type: 'success',
      });
      setForm(null);
      setConfirming(false);
      void queryClient.invalidateQueries({ queryKey: ['admin', 'maintenance'] });
      void queryClient.invalidateQueries({ queryKey: ['platform-status'] });
    },
    onError: (error) => {
      const info = errorInfo(error);
      toast({ ...info, type: 'error' });
      setConfirming(false);
    },
  });

  const payload =
    data && current ? buildPayload(data, current) : ({} as AdminMaintenanceUpdate);
  const hasChanges = Object.keys(payload).length > 1; // version alone is not a change

  return (
    <AdminPage
      eyebrow="System"
      title="Maintenance"
      description="Global maintenance switch. While enabled, every user API call answers 503 and page loads land on the public status page — the admin console keeps working so this switch can always be turned back off. Sessions are never revoked."
    >
      {isError && !isPending && (
        <QueryError
          message="Could not load maintenance state."
          onRetry={() => refetch()}
        />
      )}

      {data && current && (
        <div className="grid gap-4 lg:grid-cols-2">
          <section className="min-w-0 rounded-xl border border-border bg-surface-1 p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-border bg-surface-2">
                  <Wrench size={17} aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <h2 className="text-sm font-semibold text-foreground">
                    Current state
                  </h2>
                  <p className="text-xs text-muted-foreground">
                    {data.changed_at
                      ? `Changed ${formatDateTime(data.changed_at)}`
                      : 'Never changed'}
                    {' · v'}
                    {data.version}
                  </p>
                  {data.changed_at && (
                    <p
                      className="max-w-[220px] truncate font-mono text-[11px] text-muted-foreground"
                      title={data.changed_by ?? 'system'}
                    >
                      by {data.changed_by ?? 'system'}
                    </p>
                  )}
                </div>
              </div>
              <Pill tone={data.enabled ? 'error' : 'success'} dot>
                {data.enabled ? 'Enabled' : 'Disabled'}
              </Pill>
            </div>

            <div className="mt-5 space-y-3">
              <CheckboxRow
                checked={current.enabled}
                onChange={(next) => {
                  setForm((prev) => ({
                    ...(prev ?? fromForm(data)),
                    enabled: next,
                  }));
                }}
                title="Maintenance mode enabled"
                description="Blocks all user traffic (reads included). Healthchecks, webhooks, the public status page and the admin console stay available."
              />

              <Field label="Public title (optional)" htmlFor="maintenance-title">
                <input
                  id="maintenance-title"
                  type="text"
                  value={current.title}
                  maxLength={200}
                  onChange={(event) => {
                    const value = event.target.value;
                    setForm((prev) => ({
                      ...(prev ?? fromForm(data)),
                      title: value,
                    }));
                  }}
                  placeholder="Under maintenance"
                  className={ADMIN_INPUT_CLASS}
                />
              </Field>

              <div>
                <label htmlFor="maintenance-message" className="mb-1 block text-xs font-medium text-muted-foreground">
                  Public message (optional)
                </label>
                <textarea
                  id="maintenance-message"
                  value={current.message}
                  maxLength={1000}
                  rows={3}
                  onChange={(event) => {
                    const value = event.target.value;
                    setForm((prev) => ({
                      ...(prev ?? fromForm(data)),
                      message: value,
                    }));
                  }}
                  placeholder="Revora is receiving an upgrade. We will be back shortly."
                  className={ADMIN_TEXTAREA_CLASS}
                />
              </div>

              <Field label="Expected return (optional)" htmlFor="maintenance-eta">
                <input
                  id="maintenance-eta"
                  type="datetime-local"
                  value={current.eta}
                  onChange={(event) => {
                    const value = event.target.value;
                    setForm((prev) => ({
                      ...(prev ?? fromForm(data)),
                      eta: value,
                    }));
                  }}
                  className={ADMIN_INPUT_CLASS}
                />
              </Field>

              <Field
                label="Internal reason (never shown to users)"
                htmlFor="maintenance-reason"
              >
                <input
                  id="maintenance-reason"
                  type="text"
                  value={current.reason}
                  maxLength={500}
                  onChange={(event) => {
                    const value = event.target.value;
                    setForm((prev) => ({
                      ...(prev ?? fromForm(data)),
                      reason: value,
                    }));
                  }}
                  placeholder="e.g. DB migration, incident #42"
                  className={ADMIN_INPUT_CLASS}
                />
              </Field>

              <AdminButton
                variant="primary"
                disabled={!hasChanges || updateMutation.isPending}
                onClick={() => setConfirming(true)}
              >
                Save changes
              </AdminButton>
            </div>
          </section>

          <section className="min-w-0 rounded-xl border border-border bg-surface-1 p-5">
            <h2 className="text-sm font-semibold text-foreground">
              User-facing preview
            </h2>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              Exactly what visitors see on <code>/maintenance</code> and in the
              banner (internal reason never leaves this console).
            </p>

            <div
              role="status"
              className="mt-4 rounded-xl border border-border bg-surface-2 p-5 text-center"
            >
              <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-xl bg-warning/15 text-warning">
                <Wrench size={22} aria-hidden="true" />
              </div>
              <p className="mt-3 text-lg font-semibold text-foreground">
                {current.title.trim() || 'Under maintenance'}
              </p>
              <p className="mt-1.5 text-sm text-muted-foreground">
                {current.message.trim() ||
                  'Revora is receiving an upgrade. We will be back shortly — no action is needed on your side.'}
              </p>
              {current.eta && (
                <p className="mt-3 font-mono text-[11px] opacity-80">
                  Expected back:{' '}
                  {(() => {
                    const eta = new Date(current.eta);
                    return Number.isNaN(eta.getTime())
                      ? current.eta
                      : eta.toLocaleString();
                  })()}
                </p>
              )}
            </div>

            <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
              Recovery paths while enabled: this console, or headless{' '}
              <code className="font-mono">
                python -m scripts.admin_cli maintenance off
              </code>{' '}
              on the server.
            </p>
          </section>
        </div>
      )}

      <ConfirmDialog
        open={confirming}
        title={
          payload.enabled === undefined
            ? 'Save maintenance changes'
            : payload.enabled
              ? 'Enable maintenance mode'
              : 'Disable maintenance mode'
        }
        description={
          payload.enabled === true
            ? 'All user traffic will answer 503 and page loads will land on /maintenance. The admin console stays available.'
            : payload.enabled === false
              ? 'User traffic resumes immediately — no redeploy, no re-login needed.'
              : 'The public message will change immediately.'
        }
        confirmLabel={payload.enabled ? 'Enable' : 'Save'}
        busy={updateMutation.isPending}
        onConfirm={() => updateMutation.mutate(payload)}
        onCancel={() => {
          if (!updateMutation.isPending) setConfirming(false);
        }}
      >
        <p className="text-sm text-muted-foreground">
          The change is applied immediately and written to the audit log.
        </p>
      </ConfirmDialog>
    </AdminPage>
  );
}
