'use client';

import { type ReactNode } from 'react';

export interface DataTableColumn<T> {
  key: string;
  header: ReactNode;
  className?: string;
  render: (row: T) => ReactNode;
}

interface DataTableProps<T> {
  columns: DataTableColumn<T>[];
  rows: T[];
  keyOf: (row: T) => string;
  isLoading?: boolean;
  loadingRows?: number;
  empty?: ReactNode;
  /** Mobile (< md) card renderer; when omitted the table scrolls horizontally. */
  renderMobileCard?: (row: T) => ReactNode;
  ariaLabel?: string;
}

function ShimmerBlock({ className }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded bg-surface-2 ${className ?? ''}`}
    />
  );
}

function ShimmerRow({ cols }: { cols: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3.5">
          <ShimmerBlock className={`h-4 ${i === 0 ? 'w-40' : 'w-20'}`} />
        </td>
      ))}
    </tr>
  );
}

function ShimmerCard() {
  return (
    <div className="space-y-3 rounded-xl border border-border bg-surface-1 p-4">
      <ShimmerBlock className="h-4 w-2/3" />
      <ShimmerBlock className="h-4 w-1/2" />
    </div>
  );
}

export function DataTable<T>({
  columns,
  rows,
  keyOf,
  isLoading = false,
  loadingRows = 6,
  empty,
  renderMobileCard,
  ariaLabel,
}: DataTableProps<T>) {
  const showEmpty = !isLoading && rows.length === 0 && !!empty;

  if (showEmpty) {
    return <>{empty}</>;
  }

  const desktopTable = (
    <div
      className={`w-full max-w-full overflow-x-auto overscroll-x-contain rounded-xl border border-border bg-surface-1 ${
        renderMobileCard ? 'hidden md:block' : ''
      }`}
    >
      <table className="w-full min-w-full text-sm" aria-label={ariaLabel}>
        <thead className="bg-surface-2 text-left">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={`border-b border-border px-4 py-2.5 text-[11px] font-semibold uppercase tracking-[0.08em] text-muted-foreground ${
                  col.className ?? ''
                }`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/70">
          {isLoading
            ? Array.from({ length: loadingRows }).map((_, i) => (
                <ShimmerRow key={i} cols={columns.length} />
              ))
            : rows.map((row) => (
                <tr
                  key={keyOf(row)}
                  className="min-h-11 transition-colors hover:bg-surface-2/60"
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className={`px-4 py-3 align-middle ${col.className ?? ''}`}
                    >
                      {col.render(row)}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );

  if (!renderMobileCard) {
    return desktopTable;
  }

  return (
    <>
      <div className="space-y-3 md:hidden">
        {isLoading
          ? Array.from({ length: Math.min(loadingRows, 4) }).map((_, i) => (
              <ShimmerCard key={i} />
            ))
          : rows.map((row) => (
              <div key={keyOf(row)}>{renderMobileCard(row)}</div>
            ))}
      </div>
      {desktopTable}
    </>
  );
}
