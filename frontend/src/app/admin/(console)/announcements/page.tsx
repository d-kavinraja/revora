'use client';

import { useMemo, useState } from 'react';
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
import { TextFilter } from '@/components/shared/text-filter';
import { Pill, toneForStatus } from '@/components/shared/pill';
import { ConfirmDialog } from '@/components/shared/confirm-dialog';
import { Modal } from '@/components/shared/modal';
import {
  formatWindow,
  fromDatetimeLocalValue,
  toDatetimeLocalValue,
} from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import {
  AdminButton,
  AdminSwitch,
  ADMIN_INPUT_CLASS,
  ADMIN_TEXTAREA_CLASS,
  Field,
  FilterBar,
  SelectFilter,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const PAGE_SIZE = 25;

const KIND_LABELS: Record<string, string> = {
  scheduled_maintenance: 'Scheduled maintenance',
  upgrade: 'Upgrade',
  service_interruption: 'Service interruption',
  new_feature: 'New feature',
  provider_update: 'Provider update',
  general: 'General',
};

const KINDS = Object.keys(KIND_LABELS);

const EMPTY_ANNOUNCEMENTS: AdminAnnouncementRead[] = [];

const actionLinkCls =
  'cursor-pointer rounded text-xs font-medium focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

export default function AdminAnnouncementsPage() {
  const queryClient = useQueryClient();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState('');
  const [kindFilter, setKindFilter] = useState('');
  const [stateFilter, setStateFilter] = useState('');
  const [enabledFilter, setEnabledFilter] = useState('');
  const [editing, setEditing] = useState<AdminAnnouncementRead | null>(null);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<AdminAnnouncementRead | null>(null);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'announcements', { offset }],
    queryFn: () => adminApi.announcements(),
    retry: 1,
  });

  const items = data ?? EMPTY_ANNOUNCEMENTS;
  const filteredItems = useMemo(() => {
    const query = search.trim().toLowerCase();
    return items.filter((row) => {
      const matchesQuery =
        !query ||
        row.title.toLowerCase().includes(query) ||
        row.message.toLowerCase().includes(query);
      const matchesKind = !kindFilter || row.kind === kindFilter;
      const matchesState = !stateFilter || row.state === stateFilter;
      const matchesEnabled =
        !enabledFilter ||
        (enabledFilter === 'enabled' ? row.is_enabled : !row.is_enabled);
      return matchesQuery && matchesKind && matchesState && matchesEnabled;
    });
  }, [items, search, kindFilter, stateFilter, enabledFilter]);
  const paged = filteredItems.slice(offset, offset + PAGE_SIZE);
  const filtersActive = Boolean(search || kindFilter || stateFilter || enabledFilter);

  const createMut = useMutation({
    mutationFn: (body: AdminAnnouncementCreate) => adminApi.createAnnouncement(body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'announcements'] });
      queryClient.invalidateQueries({ queryKey: ['platform-announcements'] });
      setCreating(false);
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: AdminAnnouncementUpdate }) =>
      adminApi.updateAnnouncement(id, body),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'announcements'] });
      queryClient.invalidateQueries({ queryKey: ['platform-announcements'] });
      setEditing(null);
    },
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => adminApi.deleteAnnouncement(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['admin', 'announcements'] });
      queryClient.invalidateQueries({ queryKey: ['platform-announcements'] });
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
      render: (row) => (
        <Pill tone="muted">{KIND_LABELS[row.kind] ?? row.kind}</Pill>
      ),
    },
    {
      key: 'state',
      header: 'State',
      render: (row) => (
        <Pill
          tone={toneForStatus(row.state === 'published' ? 'active' : 'disabled')}
          dot
        >
          {row.state === 'published' ? 'Published' : 'Draft'}
        </Pill>
      ),
    },
    {
      key: 'window',
      header: 'Window',
      render: (row) => (
        <span className="text-xs text-muted-foreground">
          {formatWindow(row.starts_at, row.ends_at)}
        </span>
      ),
    },
    {
      key: 'enabled',
      header: 'Enabled',
      render: (row) => (
        <Pill tone={row.is_enabled ? 'success' : 'muted'} dot>
          {row.is_enabled ? 'Enabled' : 'Disabled'}
        </Pill>
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
      description={
        filtersActive
          ? `${filteredItems.length} of ${items.length} announcements`
          : `${items.length} announcement${items.length === 1 ? '' : 's'}`
      }
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

      <FilterBar label="Announcement filters">
        <TextFilter
          value={search}
          onChange={(value) => {
            setSearch(value);
            setOffset(0);
          }}
          placeholder="Search title or message…"
          ariaLabel="Search announcements"
          className="w-full sm:w-64"
        />
        <SelectFilter
          value={kindFilter}
          onChange={(event) => {
            setKindFilter(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter by kind"
          className="w-full sm:w-52"
        >
          <option value="">All kinds</option>
          {KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {KIND_LABELS[kind]}
            </option>
          ))}
        </SelectFilter>
        <SelectFilter
          value={stateFilter}
          onChange={(event) => {
            setStateFilter(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter by state"
          className="w-full sm:w-40"
        >
          <option value="">All states</option>
          <option value="published">Published</option>
          <option value="draft">Draft</option>
        </SelectFilter>
        <SelectFilter
          value={enabledFilter}
          onChange={(event) => {
            setEnabledFilter(event.target.value);
            setOffset(0);
          }}
          aria-label="Filter by enabled state"
          className="w-full sm:w-40"
        >
          <option value="">Enabled and disabled</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
        </SelectFilter>
      </FilterBar>

      <DataTable
        columns={columns}
        rows={paged}
        keyOf={(row) => row.id}
        isLoading={isPending}
        empty={
          <EmptyState
            icon={<Megaphone size={22} />}
            title={filtersActive ? 'No matching announcements' : 'No announcements'}
            description={
              filtersActive
                ? 'Try a different search or clear the filters.'
                : 'Create one to surface a site-wide banner on all user-facing pages, never in the admin console.'
            }
          />
        }
        ariaLabel="Announcements"
        renderMobileCard={(row) => (
          <div className="space-y-2 rounded-xl border border-border bg-surface-1 p-4">
            <p className="break-words font-medium text-foreground">{row.title}</p>
            <p className="break-words text-xs text-muted-foreground">{row.message}</p>
            <div className="flex flex-wrap items-center gap-2">
              <Pill tone="muted">{KIND_LABELS[row.kind] ?? row.kind}</Pill>
              <Pill
                tone={toneForStatus(
                  row.state === 'published' ? 'active' : 'disabled',
                )}
                dot
              >
                {row.state === 'published' ? 'Published' : 'Draft'}
              </Pill>
              <Pill tone={row.is_enabled ? 'success' : 'muted'} dot>
                {row.is_enabled ? 'Enabled' : 'Disabled'}
              </Pill>
            </div>
            <p className="text-xs text-muted-foreground">
              {formatWindow(row.starts_at, row.ends_at)}
            </p>
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

      {filteredItems.length > PAGE_SIZE && (
        <Pagination
          total={filteredItems.length}
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
  const [startsAt, setStartsAt] = useState(
    toDatetimeLocalValue(initial?.starts_at ?? null),
  );
  const [endsAt, setEndsAt] = useState(
    toDatetimeLocalValue(initial?.ends_at ?? null),
  );
  const [linkUrl, setLinkUrl] = useState(initial?.link_url ?? '');
  const [linkLabel, setLinkLabel] = useState(initial?.link_label ?? '');
  const [isEnabled, setIsEnabled] = useState(initial?.is_enabled ?? true);
  const [isDismissible, setIsDismissible] = useState(initial?.is_dismissible ?? true);

  const startsMs = startsAt ? new Date(startsAt).getTime() : null;
  const endsMs = endsAt ? new Date(endsAt).getTime() : null;
  const windowError =
    startsMs !== null && endsMs !== null && endsMs <= startsMs
      ? 'End time must be after the start time.'
      : null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (windowError) return;
    const body: AdminAnnouncementUpdate = {
      title,
      message,
      kind,
      state: initial ? state : undefined,
      starts_at: fromDatetimeLocalValue(startsAt),
      ends_at: fromDatetimeLocalValue(endsAt),
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
            disabled={
              pending ||
              !title.trim() ||
              !message.trim() ||
              Boolean(windowError)
            }
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
                  {KIND_LABELS[k]}
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
          <Field
            label="Starts at (optional)"
            htmlFor="announcement-starts"
            hint="Local time. Leave blank to start immediately."
          >
            <input
              id="announcement-starts"
              type="datetime-local"
              className={ADMIN_INPUT_CLASS}
              value={startsAt}
              onChange={(e) => setStartsAt(e.target.value)}
            />
          </Field>
          <Field
            label="Ends at (optional)"
            htmlFor="announcement-ends"
            hint="Local time. Leave blank to run until disabled."
          >
            <input
              id="announcement-ends"
              type="datetime-local"
              className={ADMIN_INPUT_CLASS}
              value={endsAt}
              onChange={(e) => setEndsAt(e.target.value)}
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

        <div className="grid gap-3 rounded-lg border border-border bg-surface-2/50 p-3 sm:grid-cols-2">
          <AdminSwitch
            checked={isEnabled}
            onChange={setIsEnabled}
            title="Enabled"
            description="Show the banner when the window is active."
          />
          <AdminSwitch
            checked={isDismissible}
            onChange={setIsDismissible}
            title="Dismissible"
            description="Let visitors close the banner."
          />
        </div>

        {initial && (
          <Field
            label="State"
            htmlFor="announcement-state"
            hint="Published announcements can appear on the public site."
          >
            <SelectFilter
              id="announcement-state"
              value={state}
              onChange={(e) => setState(e.target.value)}
              className="w-full"
            >
              <option value="draft">Draft</option>
              <option value="published">Published</option>
            </SelectFilter>
          </Field>
        )}

        <div className="rounded-lg border border-border bg-surface-2/50 p-3">
          <p className="text-xs font-medium text-muted-foreground">Preview</p>
          <div className="mt-2 rounded-md border border-brand/25 bg-brand/5 px-3 py-2.5">
            <p className="break-words text-sm font-medium text-foreground">
              {title.trim() || 'Announcement title'}
            </p>
            <p className="mt-0.5 break-words text-xs leading-relaxed text-muted-foreground">
              {message.trim() || 'Announcement message'}
            </p>
            {linkLabel.trim() && (
              <p className="mt-1 text-xs font-medium text-brand">
                {linkLabel.trim()}
              </p>
            )}
          </div>
        </div>

        {windowError && (
          <p role="alert" className="text-sm text-error">
            {windowError}
          </p>
        )}
        {error && (
          <p role="alert" className="text-sm text-error">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}
