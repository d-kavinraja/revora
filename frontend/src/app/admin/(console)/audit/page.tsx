'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, FileText } from 'lucide-react';
import {
  adminApi,
  type AdminAuditLogItem,
} from '@/lib/api';
import { DataTable, type DataTableColumn } from '@/components/shared/data-table';
import { Pagination } from '@/components/shared/pagination';
import { EmptyState } from '@/components/shared/empty-state';
import { CodeView } from '@/components/shared/code-view';
import { formatDateTime } from '@/components/shared/time-ago';

const PAGE_SIZE = 25;

const PERIODS = ['24h', '7d', '30d', 'custom'] as const;

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
        <span className="text-xs text-muted-foreground whitespace-nowrap">
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
        <span className="text-xs text-muted-foreground truncate max-w-[220px]" title={`${row.entity_type}/${row.entity_id}`}>
          {row.entity_type}/{row.entity_id}
        </span>
      ),
    },
    {
      key: 'outcome',
      header: 'Outcome',
      render: (row) => <span className="text-xs">{row.outcome ?? '—'}</span>,
    },
    {
      key: 'details',
      header: 'Details',
      render: (row) => (
        <button
          type="button"
          onClick={() => setExpanded(expanded === row.id ? null : row.id)}
          className="text-xs text-brand hover:underline"
        >
          {expanded === row.id ? 'Hide' : 'View'}
        </button>
      ),
    },
  ];

  const filterCls =
    'min-w-0 max-w-[220px] h-11 rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand';

  return (
    <div>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground">
            Audit log
          </h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {total} event{total === 1 ? '' : 's'}
          </p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <input
          className={filterCls}
          placeholder="Action"
          value={action}
          onChange={(e) => {
            setAction(e.target.value);
            setOffset(0);
          }}
        />
        <input
          className={filterCls}
          placeholder="Actor"
          value={actor}
          onChange={(e) => {
            setActor(e.target.value);
            setOffset(0);
          }}
        />
        <input
          className={filterCls}
          placeholder="Entity type"
          value={entityType}
          onChange={(e) => {
            setEntityType(e.target.value);
            setOffset(0);
          }}
        />
        <select
          className={filterCls}
          value={period}
          onChange={(e) => {
            setPeriod(e.target.value);
            setOffset(0);
          }}
          aria-label="Period"
        >
          <option value="">All time</option>
          {PERIODS.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
        {period === 'custom' && (
          <>
            <input
              className={filterCls}
              aria-label="Custom start (ISO)"
              placeholder="Start (ISO)"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
            <input
              className={filterCls}
              aria-label="Custom end (ISO)"
              placeholder="End (ISO)"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </>
        )}
      </div>

      {isError && !isPending && (
        <div
          role="alert"
          className="mt-4 flex items-center gap-3 rounded-xl border border-error/40 bg-error/10 p-4 text-sm text-error"
        >
          <AlertTriangle size={18} className="shrink-0" />
          <span>
            Could not load audit log.{' '}
            <button onClick={() => refetch()} className="underline underline-offset-2">
              Try again
            </button>
          </span>
        </div>
      )}

      <div className="mt-4">
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
            <div className="rounded-xl border border-border bg-surface-1 p-4 space-y-2">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="text-sm font-mono text-foreground break-words">{row.action}</p>
                  <p className="text-xs text-muted-foreground break-all">
                    {row.entity_type}/{row.entity_id}
                  </p>
                </div>
                <span className="text-xs text-muted-foreground whitespace-nowrap shrink-0">
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
                className="text-xs text-brand hover:underline"
              >
                {expanded === row.id ? 'Hide details' : 'View details'}
              </button>
            </div>
          )}
        />
      </div>

      {expanded && (
        <div className="mt-4">
          <CodeView
            code={JSON.stringify(
              items.find((i: AdminAuditLogItem) => i.id === expanded)?.details ?? {},
              null,
              2,
            )}
            language="json"
            title="Safe details (no secrets)"
          />
        </div>
      )}

      {total > PAGE_SIZE && (
        <Pagination
          total={total}
          limit={PAGE_SIZE}
          offset={offset}
          onChange={setOffset}
          className="mt-4"
        />
      )}
    </div>
  );
}