'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Megaphone, Plus } from 'lucide-react';
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
import { Modal } from '@/components/shared/modal';
import { formatDateTime } from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import {
  AdminButton,
  ADMIN_INPUT_CLASS,
  ADMIN_TEXTAREA_CLASS,
  CheckboxRow,
  Field,
  SelectFilter,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const PAGE_SIZE = 25;

const KINDS = [
  'scheduled_maintenance',
  'upgrade',
  'service_interruption',
  'new_feature',
  'provider_update',
  'general',
] as const;

const actionLinkCls =
  'cursor-pointer rounded text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

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
          <p className="max-w-[240px] truncate font-medium text-foreground" title={row.title}>
            {row.title}
          </p>
          <p className="max-w-[240px] truncate text-xs text-muted-foreground" title={row.message}>
            {row.message}
          </p>
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
        <Pill tone={toneForStatus(row.state === 'published' ? 'active' : 'disabled')} dot>
          {row.state}
        </Pill>
      ),
    },
    {
      key: 'window',
      header: 'Window',
      render: (row) => (
        <span className="admin-figure whitespace-nowrap text-xs text-muted-foreground">
          {row.starts_at ? formatDateTime(row.starts_at) : '—'} →{' '}
          {row.ends_at ? formatDateTime(row.ends_at) : '—'}
        </span>
      ),
    },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (row) => (
        <span className="admin-figure text-muted-foreground">
          {row.is_enabled ? 'yes' : 'no'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      className: 'text-right',
      render: (row) => (
        <div className="flex justify-end gap-3">
          <button
            type="button"
            onClick={() => setEditing(row)}
            className={`${actionLinkCls} text-brand hover:underline`}
          >
            Edit
          </button>
          <button
            type="button"
            onClick={() => setDeleting(row)}
            className={`${actionLinkCls} text-error hover:underline`}
          >
            Delete
          </button>
        </div>
      ),
    },
  ];

  return (
    <AdminPage
      eyebrow="System"
      title="Announcements"
      description={`${items.length} announcement${items.length === 1 ? '' : 's'}`}
      actions={
        <AdminButton variant="primary" onClick={() => setCreating(true)}>
          <Plus size={16} />
          New announcement
        </AdminButton>
      }
    >
      {isError && !isPending && (
        <QueryError
          message="Could not load announcements."
          onRetry={() => refetch()}
        />
      )}

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
          <div className="space-y-2 rounded-xl border border-border bg-surface-1 p-4">
            <p className="break-words font-medium text-foreground">{row.title}</p>
            <p className="break-words text-xs text-muted-foreground">{row.message}</p>
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone="muted">{row.kind}</Pill>
              <Pill tone={toneForStatus(row.state === 'published' ? 'active' : 'disabled')} dot>
                {row.state}
              </Pill>
              <span className="text-xs text-muted-foreground">
                {row.is_enabled ? 'Enabled' : 'Disabled'}
              </span>
            </div>
            <div className="flex items-center gap-3 pt-1">
              <button
                type="button"
                onClick={() => setEditing(row)}
                className={`${actionLinkCls} text-brand hover:underline`}
              >
                Edit
              </button>
              <button
                type="button"
                onClick={() => setDeleting(row)}
                className={`${actionLinkCls} text-error hover:underline`}
              >
                Delete
              </button>
            </div>
          </div>
        )}
      />

      {items.length > PAGE_SIZE && (
        <Pagination
          total={items.length}
          limit={PAGE_SIZE}
          offset={offset}
          onChange={setOffset}
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
    </AdminPage>
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

  return (
    <Modal
      open
      onClose={onCancel}
      busy={pending}
      width="max-w-2xl"
      title={initial ? 'Edit announcement' : 'New announcement'}
      footer={
        <>
          <AdminButton variant="secondary" onClick={onCancel} disabled={pending}>
            Cancel
          </AdminButton>
          <AdminButton
            type="submit"
            form="announcement-form"
            variant="primary"
            disabled={pending}
          >
            {pending ? 'Saving…' : initial ? 'Save' : 'Create (draft)'}
          </AdminButton>
        </>
      }
    >
      <form id="announcement-form" onSubmit={handleSubmit} className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Title" htmlFor="announcement-title">
            <input
              id="announcement-title"
              className={ADMIN_INPUT_CLASS}
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
              maxLength={200}
            />
          </Field>
          <Field label="Kind" htmlFor="announcement-kind">
            <SelectFilter
              id="announcement-kind"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
              className="w-full"
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </SelectFilter>
          </Field>
        </div>

        <div>
          <label
            htmlFor="announcement-message"
            className="mb-1 block text-xs font-medium text-muted-foreground"
          >
            Message
          </label>
          <textarea
            id="announcement-message"
            className={ADMIN_TEXTAREA_CLASS}
            rows={4}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            required
            maxLength={2000}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Starts at (ISO)" htmlFor="announcement-starts">
            <input
              id="announcement-starts"
              className={ADMIN_INPUT_CLASS}
              value={startsAt}
              onChange={(e) => setStartsAt(e.target.value)}
              placeholder="2026-01-01T00:00:00Z"
            />
          </Field>
          <Field label="Ends at (ISO)" htmlFor="announcement-ends">
            <input
              id="announcement-ends"
              className={ADMIN_INPUT_CLASS}
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
              placeholder="2026-01-02T00:00:00Z"
            />
          </Field>
          <Field label="Link URL" htmlFor="announcement-link-url">
            <input
              id="announcement-link-url"
              className={ADMIN_INPUT_CLASS}
              value={linkUrl}
              onChange={(e) => setLinkUrl(e.target.value)}
            />
          </Field>
          <Field label="Link label" htmlFor="announcement-link-label">
            <input
              id="announcement-link-label"
              className={ADMIN_INPUT_CLASS}
              value={linkLabel}
              onChange={(e) => setLinkLabel(e.target.value)}
            />
          </Field>
        </div>

        <div className="flex flex-wrap items-center gap-x-6 gap-y-1">
          <CheckboxRow
            checked={isEnabled}
            onChange={setIsEnabled}
            title="Enabled"
          />
          <CheckboxRow
            checked={isDismissible}
            onChange={setIsDismissible}
            title="Dismissible"
          />
          {initial && (
            <Field
              label="State"
              htmlFor="announcement-state"
              className="min-w-[160px]"
            >
              <SelectFilter
                id="announcement-state"
                value={state}
                onChange={(e) => setState(e.target.value)}
                className="w-full"
              >
                <option value="draft">draft</option>
                <option value="published">published</option>
              </SelectFilter>
            </Field>
          )}
        </div>

        {error && (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}
