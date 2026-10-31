'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { FileText } from 'lucide-react';
import {
  adminApi,
  type AdminAuditLogItem,
} from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { Pagination } from '@/components/shared/pagination';
import { EmptyState } from '@/components/shared/empty-state';
import { CodeView } from '@/components/shared/code-view';
import { Pill } from '@/components/shared/pill';
import { formatDateTime } from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import { FilterBar, SelectFilter } from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const PAGE_SIZE = 25;

const PERIODS = ['24h', '7d', '30d', 'custom'] as const;

const inputCls =
  'h-11 w-full min-w-0 rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand sm:max-w-[220px]';

export default function AdminAuditPage() {
  const [action, setAction] = useState('');
  const [actor, setActor] = useState('');
  const [entityType, setEntityType] = useState('');
  const [period, setPeriod] = useState<string>('');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [offset, setOffset] = useState(0);
  const [expanded, setExpanded] = useState<string | null>(null);

  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ['admin', 'audit', { action, actor, entityType, period, start, end, offset }],
    queryFn: () =>
      adminApi.audit({
        action: action || undefined,
        actor: actor || undefined,
        entity_type: entityType || undefined,
        period: period || undefined,
        start: period === 'custom' ? start || undefined : undefined,
        end: period === 'custom' ? end || undefined : undefined,
        limit: PAGE_SIZE,
        offset,
      }),
    retry: 1,
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  const columns: DataTableColumn<AdminAuditLogItem>[] = [
    {
      key: 'time',
      header: 'Time',
      render: (row) => (
        <span className="admin-figure whitespace-nowrap text-xs text-muted-foreground">
          {formatDateTime(row.created_at)}
        </span>
      ),
    },
    {
      key: 'actor',
      header: 'Actor',
      render: (row) => (
        <div className="min-w-0">
          <p className="text-sm text-foreground">{row.actor_id ?? '—'}</p>
          <p className="text-xs text-muted-foreground">{row.actor_type ?? ''}</p>
        </div>
      ),
    },
    {
      key: 'action',
      header: 'Action',
      render: (row) => <span className="font-mono text-xs">{row.action}</span>,
    },
    {
      key: 'target',
      header: 'Target',
      render: (row) => (
        <span
          className="block max-w-[220px] truncate text-xs text-muted-foreground"
          title={`${row.entity_type}/${row.entity_id}`}
        >
          {row.entity_type}/{row.entity_id}
        </span>
      ),
    },
    {
      key: 'outcome',
      header: 'Outcome',
      render: (row) =>
        row.outcome ? (
          <Pill
            tone={
              row.outcome === 'success'
                ? 'success'
                : row.outcome === 'failure' || row.outcome === 'error'
                  ? 'error'
                  : 'muted'
            }
            dot
          >
            {row.outcome}
          </Pill>
        ) : (
          <span className="text-xs text-muted-foreground">—</span>
        ),
    },
    {
      key: 'details',
      header: 'Details',
      render: (row) => (
        <button
          type="button"
          onClick={() => setExpanded(expanded === row.id ? null : row.id)}
          aria-expanded={expanded === row.id}
          className="cursor-pointer rounded text-xs font-medium text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
        >
          {expanded === row.id ? 'Hide' : 'View'}
        </button>
      ),
    },
  ];

  return (
    <AdminPage
      eyebrow="Monitor"
      title="Audit log"
      description={`${total} event${total === 1 ? '' : 's'}`}
    >
      <FilterBar label="Audit filters">
        <input
          className={inputCls}
          placeholder="Action"
          aria-label="Action"
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setOffset(0);
          }}
        />
        <input
          className={inputCls}
          placeholder="Actor"
          aria-label="Actor"
          value={actor}
          onChange={(e) => {
            setActor(e.target.value);
            setOffset(0);
          }}
        />
        <input
          className={inputCls}
          placeholder="Entity type"
          aria-label="Entity type"
          value={entityType}
          onChange={(e) => {
            setEntityType(e.target.value);
            setOffset(0);
          }}
        />
        <SelectFilter
          value={period}
          onChange={(e) => {
            setPeriod(e.target.value);
            setOffset(0);
          }}
          aria-label="Period"
          className="w-full sm:w-[220px]"
        >
          <option value="">All time</option>
          {PERIODS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </SelectFilter>
        {period === 'custom' && (
          <>
            <input
              className={inputCls}
              aria-label="Custom start (ISO)"
              placeholder="Start (ISO)"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
            <input
              className={inputCls}
              aria-label="Custom end (ISO)"
              placeholder="End (ISO)"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </>
        )}
      </FilterBar>

      {isError && !isPending && (
        <QueryError message="Could not load audit log." onRetry={() => refetch()} />
      )}

      <DataTable
        columns={columns}
        rows={items}
        keyOf={(row) => row.id}
        isLoading={isPending}
        empty={
          <EmptyState
            icon={<FileText size={22} />}
            title="No audit events"
            description="No events match the current filters."
          />
        }
        ariaLabel="Audit log"
        renderMobileCard={(row) => (
          <div className="space-y-2 rounded-xl border border-border bg-surface-1 p-4">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="break-words font-mono text-sm text-foreground">
                  {row.action}
                </p>
                <p className="break-all text-xs text-muted-foreground">
                  {row.entity_type}/{row.entity_id}
                </p>
              </div>
              <span className="shrink-0 whitespace-nowrap text-xs text-muted-foreground">
                {row.outcome ?? '—'}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              {row.actor_id ?? '—'}
              {row.actor_type ? ` · ${row.actor_type}` : ''}
              {' · '}
              {formatDateTime(row.created_at)}
            </p>
            <button
              type="button"
              onClick={() => setExpanded(expanded === row.id ? null : row.id)}
              aria-expanded={expanded === row.id}
              className="cursor-pointer rounded text-xs font-medium text-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
            >
              {expanded === row.id ? 'Hide details' : 'View details'}
            </button>
          </div>
        )}
      />

      {expanded && (
        <CodeView
          code={JSON.stringify(
            items.find((i: AdminAuditLogItem) => i.id === expanded)?.details ?? {},
            null,
            2,
          )}
          language="json"
          title="Safe details (no secrets)"
        />
      )}

      {total > PAGE_SIZE && (
        <Pagination
          total={total}
          limit={PAGE_SIZE}
          offset={offset}
          onChange={setOffset}
        />
      )}
    </AdminPage>
  );
}
