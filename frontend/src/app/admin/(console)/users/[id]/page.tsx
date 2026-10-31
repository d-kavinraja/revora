'use client';

import { use, useState, type KeyboardEvent } from 'react';
import Link from 'next/link';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  Ban,
  GitPullRequest,
  LogOut,
  UserCheck,
} from 'lucide-react';
import {
  adminApi,
  type AdminUserReview,
  type AdminUserRepository,
  type AdminUserCredential,
} from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { Pagination } from '@/components/shared/pagination';
import { Pill, toneForStatus } from '@/components/shared/pill';
import { StatusBadge } from '@/components/shared/status-badge';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { SkeletonList, SkeletonText } from '@/components/shared/skeleton';
import { useToast } from '@/components/ui/toaster';
import {
  formatDateTime,
  formatDateTimeWithRelative,
} from '@/components/shared/time-ago';
import { AdminButton } from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const REVIEWS_PAGE_SIZE = 10;

const TABS = [
  'Profile',
  'Repositories',
  'Credentials',
  'Reviews',
  'Errors',
  'Audit',
] as const;

type Tab = (typeof TABS)[number];

const rowButtonCls =
  'inline-flex h-9 cursor-pointer items-center rounded-lg border px-3 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-40';

const EMPTY_PANEL =
  'rounded-xl border border-dashed border-border bg-surface-1/50 p-8 text-center text-sm text-muted-foreground';

function errorDetail(error: unknown): string | undefined {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
  }
  return undefined;
}

function ProfileRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-border/70 py-2.5 last:border-0">
      <dt className="text-sm text-muted-foreground">{label}</dt>
      <dd className="break-all text-right text-sm text-foreground">{value}</dd>
    </div>
  );
}

export default function AdminUserDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = use(params);
  const [tab, setTab] = useState<Tab>('Profile');
  const [reviewsOffset, setReviewsOffset] = useState(0);
  const [disableOpen, setDisableOpen] = useState(false);
  const [enableOpen, setEnableOpen] = useState(false);
  const [revokeOpen, setRevokeOpen] = useState(false);
  const [keyDialog, setKeyDialog] = useState<{
    credential: AdminUserCredential;
    action: 'disable' | 'enable';
  } | null>(null);
  const [reason, setReason] = useState('');
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const { data, isPending, isError, refetch, isFetching } = useQuery({
    queryKey: ['admin', 'user', id, reviewsOffset],
    queryFn: () =>
      adminApi.user(id, {
        reviews_limit: REVIEWS_PAGE_SIZE,
        reviews_offset: reviewsOffset,
      }),
    retry: 1,
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ['admin', 'user', id] });
    void queryClient.invalidateQueries({ queryKey: ['admin', 'users'] });
  };

  const disableMutation = useMutation({
    mutationFn: () => adminApi.disableUser(id, { reason: reason.trim() }),
    onSuccess: () => {
      toast({ title: 'Account disabled', type: 'success' });
      setDisableOpen(false);
      setReason('');
      invalidate();
    },
    onError: (error) => {
      toast({
        title: 'Could not disable account',
        description: errorDetail(error),
        type: 'error',
      });
    },
  });

  const enableMutation = useMutation({
    mutationFn: () => adminApi.enableUser(id),
    onSuccess: () => {
      toast({ title: 'Account re-enabled', type: 'success' });
      setEnableOpen(false);
      invalidate();
    },
    onError: (error) => {
      toast({
        title: 'Could not enable account',
        description: errorDetail(error),
        type: 'error',
      });
    },
  });

  const revokeMutation = useMutation({
    mutationFn: () => adminApi.revokeUserSessions(id),
    onSuccess: () => {
      toast({ title: 'Sessions revoked', type: 'success' });
      setRevokeOpen(false);
      invalidate();
    },
    onError: (error) => {
      toast({
        title: 'Could not revoke sessions',
        description: errorDetail(error),
        type: 'error',
      });
    },
  });

  const keyDisableMutation = useMutation({
    mutationFn: (keyId: string) => adminApi.disableKey(keyId),
    onSuccess: () => {
      toast({ title: 'Credential disabled', type: 'success' });
      setKeyDialog(null);
      invalidate();
    },
    onError: (error) => {
      toast({
        title: 'Could not disable credential',
        description: errorDetail(error),
        type: 'error',
      });
    },
  });

  const keyEnableMutation = useMutation({
    mutationFn: (keyId: string) => adminApi.enableKey(keyId),
    onSuccess: () => {
      toast({ title: 'Credential re-enabled', type: 'success' });
      setKeyDialog(null);
      invalidate();
    },
    onError: (error) => {
      toast({
        title: 'Could not enable credential',
        description: errorDetail(error),
        type: 'error',
      });
    },
  });

  if (isPending) {
    return (
      <div className="space-y-6">
        <SkeletonList count={1} height="h-28" />
        <SkeletonText lines={6} />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <QueryError
        message="Could not load this user."
        onRetry={() => refetch()}
      />
    );
  }

  const { profile } = data;
  const initials = (profile.name || profile.email || '?')
    .slice(0, 1)
    .toUpperCase();

  const onTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    let next = index;
    if (event.key === 'ArrowRight') next = (index + 1) % TABS.length;
    else if (event.key === 'ArrowLeft')
      next = (index - 1 + TABS.length) % TABS.length;
    else if (event.key === 'Home') next = 0;
    else if (event.key === 'End') next = TABS.length - 1;
    else return;
    event.preventDefault();
    setTab(TABS[next]);
    document.getElementById(`user-tab-${TABS[next].toLowerCase()}`)?.focus();
  };

  const repositoryColumns: DataTableColumn<AdminUserRepository>[] = [
    {
      key: 'repo',
      header: 'Repository',
      render: (repo) => (
        <div className="min-w-0">
          <p className="max-w-[260px] truncate font-medium text-foreground" title={repo.full_name}>
            {repo.full_name}
          </p>
          <p className="text-xs text-muted-foreground">
            {[
              repo.is_private ? 'Private' : 'Public',
              repo.is_archived ? 'Archived' : null,
              repo.removed_at ? 'Removed' : null,
            ]
              .filter(Boolean)
              .join(' · ')}
          </p>
        </div>
      ),
    },
    {
      key: 'mapping',
      header: 'Configured mapping',
      render: (repo) => (
        <div className="flex items-center gap-2">
          {repo.mapping_provider || repo.mapping_model ? (
            <span className="text-foreground/80">
              {repo.mapping_provider ?? 'Unset'}
              {repo.mapping_model ? ` · ${repo.mapping_model}` : ''}
            </span>
          ) : (
            <span className="text-muted-foreground">Not configured</span>
          )}
          <Pill tone={toneForStatus(repo.mapping_health)} dot>
            {repo.mapping_health}
          </Pill>
        </div>
      ),
    },
    {
      key: 'synced',
      header: 'Last synced',
      render: (repo) => (
        <span className="admin-figure whitespace-nowrap text-muted-foreground">
          {repo.last_synced_at ? formatDateTime(repo.last_synced_at) : '—'}
        </span>
      ),
    },
    {
      key: 'removed',
      header: 'Removed',
      render: (repo) => (
        <span className="admin-figure whitespace-nowrap text-muted-foreground">
          {repo.removed_at ? formatDateTime(repo.removed_at) : '—'}
        </span>
      ),
    },
  ];

  const credentialColumns: DataTableColumn<AdminUserCredential>[] = [
    {
      key: 'label',
      header: 'Label',
      render: (cred) => (
        <div className="min-w-0">
          <p className="font-medium text-foreground">{cred.label}</p>
          <p className="text-xs text-muted-foreground">{cred.provider}</p>
        </div>
      ),
    },
    {
      key: 'valid',
      header: 'Valid',
      render: (cred) => (
        <Pill tone={cred.is_valid ? 'success' : 'error'} dot>
          {cred.is_valid ? 'Valid' : 'Invalid'}
        </Pill>
      ),
    },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (cred) => (
        <Pill tone={cred.is_enabled ? 'success' : 'muted'} dot>
          {cred.is_enabled ? 'Enabled' : 'Disabled'}
        </Pill>
      ),
    },
    {
      key: 'health',
      header: 'Last health',
      render: (cred) => (
        <div>
          {cred.last_health_status ? (
            <Pill tone={toneForStatus(cred.last_health_status)}>
              {cred.last_health_status}
            </Pill>
          ) : (
            <span className="text-muted-foreground">—</span>
          )}
          {cred.last_health_at && (
            <p className="admin-figure mt-1 text-xs text-muted-foreground">
              {formatDateTime(cred.last_health_at)}
            </p>
          )}
        </div>
      ),
    },
    {
      key: 'last_used',
      header: 'Last used',
      render: (cred) => (
        <span className="admin-figure whitespace-nowrap text-muted-foreground">
          {cred.last_used_at ? formatDateTime(cred.last_used_at) : '—'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      className: 'text-right',
      render: (cred) =>
        cred.is_enabled ? (
          <button
            type="button"
            onClick={() => setKeyDialog({ credential: cred, action: 'disable' })}
            className={`${rowButtonCls} border-error/40 text-error hover:bg-error/10`}
          >
            Disable
          </button>
        ) : (
          <button
            type="button"
            onClick={() => setKeyDialog({ credential: cred, action: 'enable' })}
            className={`${rowButtonCls} border-success/40 text-success hover:bg-success/10`}
          >
            Enable
          </button>
        ),
    },
  ];

  const reviewColumns: DataTableColumn<AdminUserReview>[] = [
    {
      key: 'pr',
      header: 'Pull request',
      render: (review) => (
        <div className="min-w-0">
          <p className="font-medium text-foreground">
            {review.repository_full_name} #{review.pr_number}
          </p>
          <p className="max-w-[320px] truncate text-xs text-muted-foreground">
            {review.pr_title}
          </p>
        </div>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (review) => <StatusBadge status={review.status} />,
    },
    {
      key: 'execution',
      header: 'Latest execution',
      render: (review) => (
        <div className="text-xs">
          <p className="text-foreground/80">
            {[review.latest_provider, review.latest_model]
              .filter(Boolean)
              .join(' · ') || '—'}
          </p>
          <p className="text-muted-foreground">
            {[
              review.latest_status,
              review.latest_duration_ms !== null
                ? `${review.latest_duration_ms.toLocaleString()} ms`
                : null,
            ]
              .filter(Boolean)
              .join(' · ') || 'Not recorded'}
          </p>
          {review.latest_error && (
            <p className="mt-1 max-w-[260px] truncate text-error" title={review.latest_error}>
              {review.latest_error}
            </p>
          )}
        </div>
      ),
    },
    {
      key: 'created',
      header: 'Created',
      render: (review) => (
        <span className="admin-figure whitespace-nowrap text-muted-foreground">
          {formatDateTime(review.created_at)}
        </span>
      ),
    },
  ];

  return (
    <div className="min-w-0">
      <Link
        href="/admin/users"
        className="inline-flex items-center gap-2 rounded text-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      >
        <ArrowLeft size={15} />
        Back to users
      </Link>

      <header className="mt-4 flex flex-wrap items-start justify-between gap-4 rounded-xl border border-border bg-surface-1 p-5">
        <div className="flex min-w-0 items-center gap-4">
          {profile.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={profile.avatar_url}
              alt=""
              className="h-14 w-14 shrink-0 rounded-full border border-border object-cover"
            />
          ) : (
            <span className="flex h-14 w-14 shrink-0 items-center justify-center rounded-full border border-brand/30 bg-brand/15 text-xl font-semibold text-brand">
              {initials}
            </span>
          )}
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="truncate text-xl font-bold tracking-tight text-foreground md:text-2xl">
                {profile.name || '—'}
              </h1>
              <Pill tone={profile.status === 'disabled' ? 'muted' : toneForStatus(profile.status)} dot>
                {profile.status}
              </Pill>
              {profile.is_verified && (
                <Pill tone="success" dot>
                  Verified
                </Pill>
              )}
              <Pill tone="brand">{profile.role}</Pill>
            </div>
            <p className="truncate text-sm text-muted-foreground">{profile.email}</p>
            {profile.github_username && (
              <p className="text-xs text-muted-foreground">@{profile.github_username}</p>
            )}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <div className="flex flex-wrap items-center gap-2">
            {profile.status === 'disabled' ? (
              <AdminButton
                variant="successSoft"
                onClick={() => setEnableOpen(true)}
              >
                <UserCheck size={16} />
                Enable account
              </AdminButton>
            ) : (
              <AdminButton variant="dangerSoft" onClick={() => setDisableOpen(true)}>
                <Ban size={16} />
                Disable account
              </AdminButton>
            )}
            <AdminButton variant="secondary" onClick={() => setRevokeOpen(true)}>
              <LogOut size={16} />
              Revoke sessions
            </AdminButton>
          </div>
          <p className="h-4 text-xs text-muted-foreground">
            {isFetching ? 'Refreshing…' : null}
          </p>
        </div>
      </header>

      <div
        role="tablist"
        aria-label="User sections"
        className="mt-6 flex items-center gap-1 overflow-x-auto border-b border-border"
      >
        {TABS.map((entry, index) => {
          const active = tab === entry;
          return (
            <button
              key={entry}
              id={`user-tab-${entry.toLowerCase()}`}
              type="button"
              role="tab"
              aria-selected={active}
              aria-controls="user-tabpanel"
              tabIndex={active ? 0 : -1}
              onClick={() => setTab(entry)}
              onKeyDown={(event) => onTabKeyDown(event, index)}
              className={`-mb-px h-11 cursor-pointer whitespace-nowrap rounded-t-lg border-b-2 px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
                active
                  ? 'border-brand text-brand'
                  : 'border-transparent text-foreground/70 hover:text-foreground'
              }`}
            >
              {entry}
              {entry === 'Reviews' ? ` (${data.reviews.total})` : ''}
            </button>
          );
        })}
      </div>

      <div
        role="tabpanel"
        id="user-tabpanel"
        aria-labelledby={`user-tab-${tab.toLowerCase()}`}
        className="mt-6"
      >
        {tab === 'Profile' && (
          <section className="max-w-2xl rounded-xl border border-border bg-surface-1 p-5">
            <dl>
              <ProfileRow label="User ID" value={<span className="font-mono text-xs">{profile.id}</span>} />
              <ProfileRow label="Default provider" value={profile.default_provider ?? '—'} />
              <ProfileRow label="Created" value={formatDateTimeWithRelative(profile.created_at)} />
              <ProfileRow
                label="Last login"
                value={profile.last_login_at ? formatDateTimeWithRelative(profile.last_login_at) : 'Not recorded'}
              />
              <ProfileRow
                label="Last active"
                value={profile.last_active_at ? formatDateTimeWithRelative(profile.last_active_at) : 'Not recorded'}
              />
              <ProfileRow
                label="Disabled at"
                value={profile.disabled_at ? formatDateTimeWithRelative(profile.disabled_at) : '—'}
              />
            </dl>
          </section>
        )}

        {tab === 'Repositories' && (
          <DataTable
            columns={repositoryColumns}
            rows={data.repositories}
            keyOf={(repo) => repo.id}
            empty={<p className={EMPTY_PANEL}>No repositories connected.</p>}
            ariaLabel="User repositories"
            renderMobileCard={(repo) => (
              <div className="space-y-2 rounded-xl border border-border bg-surface-1 p-4">
                <p className="break-words font-medium text-foreground">{repo.full_name}</p>
                <p className="text-xs text-muted-foreground">
                  {[
                    repo.is_private ? 'Private' : 'Public',
                    repo.is_archived ? 'Archived' : null,
                    repo.removed_at ? 'Removed' : null,
                  ]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
                <div className="flex min-w-0 items-center gap-2">
                  <span className="truncate text-xs text-foreground/80">
                    {repo.mapping_provider || repo.mapping_model
                      ? `${repo.mapping_provider ?? 'Unset'}${repo.mapping_model ? ` · ${repo.mapping_model}` : ''}`
                      : 'Not configured'}
                  </span>
                  <Pill tone={toneForStatus(repo.mapping_health)} dot>
                    {repo.mapping_health}
                  </Pill>
                </div>
              </div>
            )}
          />
        )}

        {tab === 'Credentials' && (
          <div>
            <p className="mb-3 text-xs text-muted-foreground">
              Metadata only — key material is never exposed.
            </p>
            <DataTable
              columns={credentialColumns}
              rows={data.credentials}
              keyOf={(cred) => cred.id}
              empty={<p className={EMPTY_PANEL}>No credentials stored.</p>}
              ariaLabel="User credentials"
            />
          </div>
        )}

        {tab === 'Reviews' && (
          <div>
            {Object.keys(data.reviews.status_counts).length > 0 && (
              <ul className="mb-4 flex flex-wrap gap-2">
                {Object.entries(data.reviews.status_counts).map(([status, count]) => (
                  <li
                    key={status}
                    className="inline-flex items-center gap-2 rounded-full border border-border bg-surface-2 px-3 py-1 text-xs"
                  >
                    <StatusBadge status={status} />
                    <span className="admin-figure font-semibold text-foreground">
                      {count}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            <DataTable
              columns={reviewColumns}
              rows={data.reviews.items}
              keyOf={(review) => review.id}
              empty={<p className={EMPTY_PANEL}>No reviews created.</p>}
              ariaLabel="User reviews"
            />
            <Pagination
              total={data.reviews.total}
              limit={REVIEWS_PAGE_SIZE}
              offset={reviewsOffset}
              onChange={setReviewsOffset}
              className="mt-4"
            />
          </div>
        )}

        {tab === 'Errors' && (
          <div className="space-y-3">
            {data.recent_errors.length === 0 ? (
              <p className={EMPTY_PANEL}>No recent errors.</p>
            ) : (
              data.recent_errors.map((error, index) => (
                <div
                  key={index}
                  className="rounded-xl border border-border bg-surface-1 p-4 text-sm"
                >
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <span className="font-medium text-foreground">
                      {error.provider ?? 'Unknown provider'}
                    </span>
                    <span className="admin-figure text-xs text-muted-foreground">
                      {error.occurred_at
                        ? formatDateTimeWithRelative(error.occurred_at)
                        : '—'}
                    </span>
                  </div>
                  <p className="mt-1 break-words font-mono text-xs text-error/90">
                    {error.message}
                  </p>
                </div>
              ))
            )}
          </div>
        )}

        {tab === 'Audit' && (
          <div className="space-y-2">
            {data.audit_events.length === 0 ? (
              <p className={EMPTY_PANEL}>No admin events recorded for this user.</p>
            ) : (
              data.audit_events.map((event) => (
                <div
                  key={event.id}
                  className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface-1 p-3 text-sm"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <GitPullRequest size={15} className="shrink-0 text-muted-foreground" />
                    <span className="font-medium text-foreground">{event.action}</span>
                    <Pill tone="muted">{event.actor_type}</Pill>
                    {event.outcome && (
                      <Pill tone={toneForStatus(event.outcome)}>{event.outcome}</Pill>
                    )}
                  </div>
                  <span className="admin-figure text-xs text-muted-foreground">
                    {formatDateTimeWithRelative(event.created_at)}
                  </span>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={disableOpen}
        title="Disable this account?"
        description={`${profile.name || profile.email} will be blocked from the API immediately and all live sessions will be signed out. Data, keys, and mappings are preserved; access can be restored at any time.`}
        confirmLabel="Disable account"
        tone="danger"
        busy={disableMutation.isPending}
        confirmDisabled={reason.trim().length === 0}
        onConfirm={() => disableMutation.mutate()}
        onCancel={() => {
          setDisableOpen(false);
          setReason('');
        }}
      >
        <label
          htmlFor="disable-reason"
          className="block text-sm font-medium text-foreground"
        >
          Reason <span className="text-muted-foreground">(recorded in the audit log)</span>
        </label>
        <textarea
          id="disable-reason"
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          maxLength={500}
          rows={3}
          required
          className="mt-2 w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          placeholder="e.g. Terms of service violation (ticket #123)"
        />
      </ConfirmDialog>

      <ConfirmDialog
        open={enableOpen}
        title="Re-enable this account?"
        description="The user will be able to sign in and use the platform again. Keys and mappings were never touched."
        confirmLabel="Enable account"
        busy={enableMutation.isPending}
        onConfirm={() => enableMutation.mutate()}
        onCancel={() => setEnableOpen(false)}
      />

      <ConfirmDialog
        open={revokeOpen}
        title="Revoke all sessions?"
        description="Every active session for this user is signed out immediately. They can sign in again with valid credentials."
        confirmLabel="Revoke sessions"
        tone="danger"
        busy={revokeMutation.isPending}
        onConfirm={() => revokeMutation.mutate()}
        onCancel={() => setRevokeOpen(false)}
      />

      <ConfirmDialog
        open={keyDialog !== null}
        title={
          keyDialog?.action === 'disable'
            ? 'Disable this credential?'
            : 'Re-enable this credential?'
        }
        description={
          keyDialog?.action === 'disable'
            ? `"${keyDialog.credential.label}" (${keyDialog.credential.provider}) will be excluded from provider selection for this user. Key material, mappings, and review history are untouched.`
            : `"${keyDialog?.credential.label}" (${keyDialog?.credential.provider}) becomes selectable again immediately — no user reconfiguration needed.`
        }
        confirmLabel={
          keyDialog?.action === 'disable'
            ? 'Disable credential'
            : 'Enable credential'
        }
        tone={keyDialog?.action === 'disable' ? 'danger' : 'default'}
        busy={keyDisableMutation.isPending || keyEnableMutation.isPending}
        onConfirm={() => {
          if (!keyDialog) return;
          if (keyDialog.action === 'disable') {
            keyDisableMutation.mutate(keyDialog.credential.id);
          } else {
            keyEnableMutation.mutate(keyDialog.credential.id);
          }
        }}
        onCancel={() => {
          if (!keyDisableMutation.isPending && !keyEnableMutation.isPending) {
            setKeyDialog(null);
          }
        }}
      />
    </div>
  );
}
