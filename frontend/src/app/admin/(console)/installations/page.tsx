'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { adminApi } from '@/lib/api';
import { Pill, toneForStatus } from '@/components/shared/pill';

export default function AdminInstallationsPage() {
  const [status, setStatus] = useState('');
  const [q, setQ] = useState('');
  const [offset, setOffset] = useState(0);
  const limit = 50;

  const { data, isLoading } = useQuery({
    queryKey: ['admin', 'installations', status, q, offset],
    queryFn: () =>
      adminApi.installations({
        status: status || undefined,
        q: q || undefined,
        limit,
        offset,
      }),
  });

  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOffset(0);
          }}
          placeholder="Search account or installation ID"
          className="h-9 rounded-lg border border-border bg-surface-1 px-3 text-sm"
        />
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value);
            setOffset(0);
          }}
          className="h-9 rounded-lg border border-border bg-surface-1 px-3 text-sm"
        >
          <option value="">All statuses</option>
          <option value="active">active</option>
          <option value="suspended">suspended</option>
          <option value="inaccessible">inaccessible</option>
          <option value="reauthorization_required">reauthorization_required</option>
          <option value="configuration_error">configuration_error</option>
        </select>
      </div>

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead className="bg-surface-2 text-left">
            <tr>
              <th className="px-3 py-2">Account</th>
              <th className="px-3 py-2">Installation ID</th>
              <th className="px-3 py-2">App ID</th>
              <th className="px-3 py-2">Lifecycle</th>
              <th className="px-3 py-2">Permissions</th>
              <th className="px-3 py-2">Repos</th>
              <th className="px-3 py-2">Last auth check</th>
              <th className="px-3 py-2">Retry after</th>
              <th className="px-3 py-2">Last sync</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr>
                <td className="px-3 py-4" colSpan={9}>
                  Loading...
                </td>
              </tr>
            ) : items.length === 0 ? (
              <tr>
                <td className="px-3 py-4" colSpan={9}>
                  No installations found.
                </td>
              </tr>
            ) : (
              items.map((item) => (
                <tr key={item.id} className="border-t border-border">
                  <td className="px-3 py-2">{item.account_login ?? '-'}</td>
                  <td className="px-3 py-2 font-mono">{item.installation_id}</td>
                  <td className="px-3 py-2 font-mono">{item.app_id ?? '-'}</td>
                  <td className="px-3 py-2">
                    <Pill tone={toneForStatus(item.lifecycle_status)}>
                      {item.lifecycle_status}
                    </Pill>
                  </td>
                  <td className="px-3 py-2">
                    {item.permissions_ok === null
                      ? '-'
                      : item.permissions_ok
                        ? 'ok'
                        : 'missing'}
                  </td>
                  <td className="px-3 py-2">{item.repository_count}</td>
                  <td className="px-3 py-2">
                    {item.last_auth_checked_at
                      ? new Date(item.last_auth_checked_at).toLocaleString()
                      : '-'}
                  </td>
                  <td className="px-3 py-2">
                    {item.retry_after ? new Date(item.retry_after).toLocaleString() : '-'}
                  </td>
                  <td className="px-3 py-2">
                    {item.last_sync_status ?? '-'}
                    {item.last_auth_error_category
                      ? ` (${item.last_auth_error_category})`
                      : ''}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex items-center justify-between text-sm">
        <span>
          Showing {items.length} of {total}
        </span>
        <div className="flex gap-2">
          <button
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - limit))}
            className="rounded-lg border border-border px-3 py-1 disabled:opacity-50"
          >
            Previous
          </button>
          <button
            disabled={offset + limit >= total}
            onClick={() => setOffset(offset + limit)}
            className="rounded-lg border border-border px-3 py-1 disabled:opacity-50"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}
