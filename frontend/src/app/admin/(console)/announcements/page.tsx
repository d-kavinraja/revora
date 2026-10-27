'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { AlertTriangle, Megaphone, Plus } from 'lucide-react';
import {
  adminApi,
  type AdminAnnouncementRead,
  type AdminAnnouncementCreate,
  type AdminAnnouncementUpdate,
} from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { Pagination } from '@/components/shared/pagination';
import { EmptyState } from '@/components/shared/empty-state';
import { Pill, toneForStatus } from '@/components/shared/pill';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { formatDateTime } from '@/components/shared/time-ago';

const PAGE_SIZE = 25;

const KINDS = [
  'scheduled_maintenance',
  'upgrade',
  'service_interruption',
  'new_feature',
  'provider_update',
  'general',
] as const;

export default function AdminAnnouncementsPage() {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [editing, setEditing] = useState<AdminAnnouncementRead | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<AdminAnnouncementRead | null>(null);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'announcements', { offset }],
    queryFn: () => adminApi.announcements(),
    retry: 1,
  });

  const items = data ?? [];
  const paged = items.slice(offset, offset + PAGE_SIZE);

  const createMut = useMutation({
    mutationFn: (body: AdminAnnouncementCreate) => adminApi.createAnnouncement(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'announcements'] });
      setCreating(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: AdminAnnouncementUpdate }) =>
      adminApi.updateAnnouncement(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'announcements'] });
      setEditing(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => adminApi.deleteAnnouncement(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'announcements'] });
      setDeleting(null);
    },
  });

  const columns: DataTableColumn<AdminAnnouncementRead>[] = [
    {
      key: 'title',
      header: 'Title',
      render: (row) => (
        <div className="min-w-0">
          <p className="font-medium text-foreground truncate max-w-[240px]" title={row.title}>{row.title}</p>
          <p className="text-xs text-muted-foreground truncate max-w-[240px]" title={row.message}>{row.message}</p>
        </div>
      ),
    },
    {
      key: 'kind',
      header: 'Kind',
      render: (row) => <Pill tone="muted">{row.kind}</Pill>,
    },
    {
      key: 'state',
      header: 'State',
      render: (row) => (
        <Pill tone={toneForStatus(row.state === 'published' ? 'active' : 'disabled')}>
          {row.state}
        </Pill>
      ),
    },
    {
      key: 'window',
      header: 'Window',
      render: (row) => (
        <span className="text-xs text-muted-foreground whitespace-nowrap">
          {row.starts_at ? formatDateTime(row.starts_at) : '—'} →{' '}
          {row.ends_at ? formatDateTime(row.ends_at) : '—'}
        </span>
      ),
    },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (row) => <span className="tabular-nums">{row.is_enabled ? 'yes' : 'no'}</span>,
    },
    {
      key: 'actions',
      header: '',
      className: 'text-right',
      render: (row) => (
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => setEditing(row)}
            className="text-xs text-brand hover:underline"
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => setDeleting(row)}
            className="text-xs text-error hover:underline"
          >
            Delete
          </button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
            Announcements
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {items.length} announcement{items.length === 1 ? '' : 's'}
          </p>
        </div>
        <button
          type="button"
          onClick={() => setCreating(true)}
          className="inline-flex items-center gap-2 rounded-lg bg-brand px-4 py-2 text-sm font-medium text-brand-foreground hover:bg-brand/90"
        >
          <Plus size={16} /> New announcement
        </button>
      </div>

      {isError && !isPending && (
        <div
          role="alert"
          className="mt-4 flex items-center gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error"
        >
          <AlertTriangle size={18} className="shrink-0" />
          <span>
            Could not load announcements.{' '}
            <button onClick={() => refetch()} className="underline underline-offset-2">
              Try again
            </button>
          </span>
        </div>
      )}

      <div className="mt-4">
        <DataTable
          columns={columns}
          rows={paged}
          keyOf={(row) => row.id}
          isLoading={isPending}
          empty={
            <EmptyState
              icon={<Megaphone size={22} />}
              title="No announcements"
              description="Create one to surface a landing-page banner."
            />
          }
          ariaLabel="Announcements"
          renderMobileCard={(row) => (
            <div className="rounded-xl border border-border bg-surface-1 p-4 space-y-2">
              <p className="font-medium text-foreground break-words">{row.title}</p>
              <p className="text-xs text-muted-foreground break-words">{row.message}</p>
              <div className="flex flex-wrap items-center gap-2">
                <Pill tone="muted">{row.kind}</Pill>
                <Pill tone={toneForStatus(row.state === 'published' ? 'active' : 'disabled')}>
                  {row.state}
                </Pill>
                <span className="text-xs text-muted-foreground">
                  {row.is_enabled ? 'Enabled' : 'Disabled'}
                </span>
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={() => setEditing(row)}
                  className="text-xs text-brand hover:underline"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => setDeleting(row)}
                  className="text-xs text-error hover:underline"
                >
                  Delete
                </button>
              </div>
            </div>
          )}
        />
      </div>

      {items.length > PAGE_SIZE && (
        <Pagination
          total={items.length}
          limit={PAGE_SIZE}
          offset={offset}
          onChange={setOffset}
          className="mt-4"
        />
      )}

      {(creating || editing) && (
        <AnnouncementEditor
          initial={editing}
          onCancel={() => {
            setCreating(false);
            setEditing(null);
          }}
          onSubmit={(body) => {
            if (editing) {
              updateMut.mutate({ id: editing.id, body });
            } else {
              createMut.mutate(body as AdminAnnouncementCreate);
            }
          }}
          pending={createMut.isPending || updateMut.isPending}
          error={(createMut.error ?? updateMut.error)?.message ?? null}
        />
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Delete announcement"
        description={
          deleting ? `Delete "${deleting.title}"? This cannot be undone.` : ''
        }
        confirmLabel="Delete"
        tone="danger"
        onConfirm={() => deleting && deleteMut.mutate(deleting.id)}
        onCancel={() => setDeleting(null)}
      />
    </div>
  );
}

function AnnouncementEditor({
  initial,
  onCancel,
  onSubmit,
  pending,
  error,
}: {
  initial: AdminAnnouncementRead | null;
  onCancel: () => void;
  onSubmit: (body: AdminAnnouncementCreate | AdminAnnouncementUpdate) => void;
  pending: boolean;
  error: string | null;
}) {
  const [title, setTitle] = useState(initial?.title ?? '');
  const [message, setMessage] = useState(initial?.message ?? '');
  const [kind, setKind] = useState(initial?.kind ?? 'general');
  const [state, setState] = useState(initial?.state ?? 'draft');
  const [startsAt, setStartsAt] = useState(initial?.starts_at ?? '');
  const [endsAt, setEndsAt] = useState(initial?.ends_at ?? '');
  const [linkUrl, setLinkUrl] = useState(initial?.link_url ?? '');
  const [linkLabel, setLinkLabel] = useState(initial?.link_label ?? '');
  const [isEnabled, setIsEnabled] = useState(initial?.is_enabled ?? true);
  const [isDismissible, setIsDismissible] = useState(initial?.is_dismissible ?? true);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const body: AdminAnnouncementUpdate = {
      title,
      message,
      kind,
      state: initial ? state : undefined,
      starts_at: startsAt || null,
      ends_at: endsAt || null,
      link_url: linkUrl || null,
      link_label: linkLabel || null,
      is_enabled: isEnabled,
      is_dismissible: isDismissible,
    };
    onSubmit(body);
  };

  const inputCls =
    'h-11 w-full rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-2xl space-y-4 rounded-xl border border-border bg-surface-1 p-6 shadow-xl max-h-[90dvh] overflow-y-auto"
      >
        <h2 className="text-lg font-semibold text-foreground">
          {initial ? 'Edit announcement' : 'New announcement'}
        </h2>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Title</span>
            <input className={inputCls} value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={200} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Kind</span>
            <select className={inputCls} value={kind} onChange={(e) => setKind(e.target.value)}>
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label className="space-y-1 text-sm block">
          <span className="text-muted-foreground">Message</span>
          <textarea
            className="w-full rounded-lg border border-border bg-surface-1 px-3 py-2 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            rows={4}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            required
            maxLength={2000}
          />
        </label>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Starts at (ISO)</span>
            <input className={inputCls} value={startsAt} onChange={(e) => setStartsAt(e.target.value)} placeholder="2026-01-01T00:00:00Z" />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Ends at (ISO)</span>
            <input className={inputCls} value={endsAt} onChange={(e) => setEndsAt(e.target.value)} placeholder="2026-01-02T00:00:00Z" />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Link URL</span>
            <input className={inputCls} value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} />
          </label>
          <label className="space-y-1 text-sm">
            <span className="text-muted-foreground">Link label</span>
            <input className={inputCls} value={linkLabel} onChange={(e) => setLinkLabel(e.target.value)} />
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-4 text-sm">
          <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={isEnabled} onChange={(e) => setIsEnabled(e.target.checked)} />
            Enabled
          </label>
          <label className="inline-flex items-center gap-2">
            <input type="checkbox" checked={isDismissible} onChange={(e) => setIsDismissible(e.target.checked)} />
            Dismissible
          </label>
          {initial && (
            <label className="space-y-1 text-sm">
              <span className="text-muted-foreground mr-2">State</span>
              <select className={inputCls} value={state} onChange={(e) => setState(e.target.value)}>
                <option value="draft">draft</option>
                <option value="published">published</option>
              </select>
            </label>
          )}
        </div>
        {error && <p className="text-sm text-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-lg border border-border px-4 py-2 text-sm">
            Cancel
          </button>
          <button
            type="submit"
            disabled={pending}
            className="rounded-lg bg-brand px-4 py-2 text-sm font-medium text-brand-foreground hover:bg-brand/90 disabled:opacity-60"
          >
            {pending ? 'Saving…' : initial ? 'Save' : 'Create (draft)'}
          </button>
        </div>
      </form>
    </div>
  );
}
