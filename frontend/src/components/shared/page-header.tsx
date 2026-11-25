import { type ReactNode } from 'react';

/**
 * Canonical page header: H1 (Oxanium "instrument voice") + one support line,
 * with every page action in a single right-aligned cluster. On small screens
 * the action cluster wraps below the title instead of floating mid-page.
 */
export function PageHeader({
  title,
  support,
  actions,
  icon,
}: {
  title: string;
  support?: string;
  actions?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
      <div className="min-w-0">
        <h1 className="flex items-center gap-2 text-2xl font-heading font-bold tracking-tight text-foreground md:text-3xl">
          {icon}
          {title}
        </h1>
        {support && (
          <p className="mt-1 max-w-[72ch] text-sm text-muted-foreground md:text-base">
            {support}
          </p>
        )}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}