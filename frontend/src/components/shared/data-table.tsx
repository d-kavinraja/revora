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
      className={`rounded bg-muted/50 dark:bg-surface-2 animate-pulse ${className ?? ''}`}
    />
  );
}

function ShimmerRow({ cols }: { cols: number }) {
  return (
    <tr>
      {Array.from({ length: cols }).map((_, i) => (
        <td key={i} className="px-4 py-3">
          <ShimmerBlock className="h-4" />
        </td>
      ))}
    </tr>
  );
}

function ShimmerCard() {
  return (
    <div className="rounded-xl border border-border bg-surface-1 p-4 space-y-3">
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
  loadingRows = 5,
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
      className={`w-full max-w-full overflow-x-auto overscroll-x-contain rounded-xl border border-border ${
        renderMobileCard ? 'hidden md:block' : ''
      }`}
    >
      <table className="w-full min-w-full text-sm" aria-label={ariaLabel}>
        <thead className="bg-surface-2 text-left text-xs uppercase tracking-wide text-muted-foreground">
          <tr>
            {columns.map((col) => (
              <th
                key={col.key}
                scope="col"
                className={`px-4 py-3 font-medium ${col.className ?? ''}`}
              >
                {col.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {isLoading
            ? Array.from({ length: loadingRows }).map((_, i) => (
                <ShimmerRow key={i} cols={columns.length} />
              ))
            : rows.map((row) => (
                <tr
                  key={keyOf(row)}
                  className="hover:bg-surface-2/60 transition-colors"
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
      <div className="md:hidden space-y-3">
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
