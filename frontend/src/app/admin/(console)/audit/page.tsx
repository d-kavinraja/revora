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
import { TextFilter } from '@/components/shared/text-filter';
import {
  formatDateTime,
  fromDatetimeLocalValue,
} from '@/components/shared/time-ago';
import { AdminPage } from '@/components/admin/page-shell';
import {
  ADMIN_INPUT_CLASS,
  FilterBar,
  SelectFilter,
} from '@/components/admin/controls';
import { QueryError } from '@/components/admin/states';

const PAGE_SIZE = 25;

const PERIODS = [
  { value: '24h', label: 'Last 24 hours' },
  { value: '7d', label: 'Last 7 days' },
  { value: '30d', label: 'Last 30 days' },
  { value: 'custom', label: 'Custom range' },
] as const;

const dateCls = `${ADMIN_INPUT_CLASS} sm:max-w-[220px]`;

function humanize(value: string): string {
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ');
}

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
        start:
          period === 'custom'
            ? fromDatetimeLocalValue(start) ?? undefined
            : undefined,
        end:
          period === 'custom'
            ? fromDatetimeLocalValue(end) ?? undefined
            : undefined,
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
          <p className="text-xs text-muted-foreground">
            {row.actor_type ? humanize(row.actor_type) : ''}
          </p>
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
            {humanize(row.outcome)}
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
        <TextFilter
          value={action}
          onChange={(value) => {
            setAction(value);
            setOffset(0);
          }}
          placeholder="Action…"
          ariaLabel="Filter by action"
          className="w-full sm:w-44"
        />
        <TextFilter
          value={actor}
          onChange={(value) => {
            setActor(value);
            setOffset(0);
          }}
          placeholder="Actor…"
          ariaLabel="Filter by actor"
          className="w-full sm:w-44"
        />
        <TextFilter
          value={entityType}
          onChange={(value) => {
            setEntityType(value);
            setOffset(0);
          }}
          placeholder="Entity type…"
          ariaLabel="Filter by entity type"
          className="w-full sm:w-44"
        />
        <SelectFilter
          value={period}
          onChange={(event) => {
            setPeriod(event.target.value);
            setOffset(0);
            setExpanded(null);
          }}
          aria-label="Filter by period"
          className="w-full sm:w-44"
        >
          <option value="">All time</option>
          {PERIODS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </SelectFilter>
        {period === 'custom' && (
          <>
            <input
              type="datetime-local"
              className={dateCls}
              aria-label="Custom start"
              value={start}
              onChange={(event) => {
                setStart(event.target.value);
                setOffset(0);
              }}
            />
            <input
              type="datetime-local"
              className={dateCls}
              aria-label="Custom end"
              value={end}
              onChange={(event) => {
                setEnd(event.target.value);
                setOffset(0);
              }}
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
            title={
              action || actor || entityType || period
                ? 'No matching audit events'
                : 'No audit events'
            }
            description={
              action || actor || entityType || period
                ? 'Try a different search or widen the time range.'
                : 'Admin actions will appear here as they happen.'
            }
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
              {row.outcome ? (
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
                  {humanize(row.outcome)}
                </Pill>
              ) : (
                <span className="shrink-0 text-xs text-muted-foreground">
                  —
                </span>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              {row.actor_id ?? '—'}
              {row.actor_type ? ` · ${humanize(row.actor_type)}` : ''}
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
