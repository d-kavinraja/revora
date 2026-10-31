'use client';

import { ChevronLeft, ChevronRight } from 'lucide-react';

interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onChange: (offset: number) => void;
  className?: string;
}

/** Condensed page window: first, last, and current ± 1, with ellipses. */
function pageWindow(current: number, pages: number): Array<number | '…'> {
  const candidates = new Set<number>([1, pages, current - 1, current, current + 1]);
  const visible = [...candidates]
    .filter((p) => p >= 1 && p <= pages)
    .sort((a, b) => a - b);
  const result: Array<number | '…'> = [];
  let previous = 0;
  for (const page of visible) {
    if (previous && page - previous > 1) result.push('…');
    result.push(page);
    previous = page;
  }
  return result;
}

export function Pagination({ total, limit, offset, onChange, className }: PaginationProps) {
  const pages = Math.max(1, Math.ceil(total / Math.max(1, limit)));
  const current = Math.min(pages, Math.floor(offset / Math.max(1, limit)) + 1);
  const first = total === 0 ? 0 : offset + 1;
  const last = Math.min(offset + limit, total);

  const goTo = (page: number) => {
    const next = Math.min(Math.max(1, page), pages);
    if (next !== current) onChange((next - 1) * limit);
  };

  const buttonCls =
    'inline-flex min-w-11 h-11 items-center justify-center rounded-lg border text-sm font-medium transition-colors cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:opacity-40 disabled:cursor-not-allowed';

  return (
    <nav
      aria-label="Pagination"
      className={`flex flex-wrap items-center justify-between gap-3 ${className ?? ''}`}
    >
      <p className="admin-figure text-xs text-muted-foreground" aria-live="polite">
        {total === 0 ? 'No results' : `Showing ${first}–${last} of ${total}`}
      </p>

      {pages > 1 && (
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => goTo(current - 1)}
            disabled={current <= 1}
            aria-label="Previous page"
            className={`${buttonCls} border-border text-foreground/80 hover:bg-surface-2`}
          >
            <ChevronLeft size={16} />
          </button>

          {pageWindow(current, pages).map((entry, index) =>
            entry === '…' ? (
              <span
                key={`ellipsis-${index}`}
                className="px-1 text-sm text-muted-foreground"
                aria-hidden="true"
              >
                …
              </span>
            ) : (
              <button
                key={entry}
                type="button"
                onClick={() => goTo(entry)}
                aria-label={`Page ${entry}`}
                aria-current={entry === current ? 'page' : undefined}
                className={`${buttonCls} ${
                  entry === current
                    ? 'border-brand/40 bg-brand/10 text-brand'
                    : 'border-border text-foreground/80 hover:bg-surface-2'
                }`}
              >
                {entry}
              </button>
            ),
          )}

          <button
            type="button"
            onClick={() => goTo(current + 1)}
            disabled={current >= pages}
            aria-label="Next page"
            className={`${buttonCls} border-border text-foreground/80 hover:bg-surface-2`}
          >
            <ChevronRight size={16} />
          </button>
        </div>
      )}
    </nav>
  );
}
