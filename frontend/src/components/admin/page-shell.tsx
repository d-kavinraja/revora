import { type ReactNode } from 'react';

interface AdminPageProps {
  eyebrow?: string;
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  meta?: ReactNode;
  children?: ReactNode;
}

export function AdminPage({
  eyebrow,
  title,
  description,
  actions,
  meta,
  children,
}: AdminPageProps) {
  return (
    <div className="min-w-0">
      <header className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 max-w-3xl">
          {eyebrow && <p className="admin-eyebrow">{eyebrow}</p>}
          <h1 className="mt-1 text-2xl font-bold tracking-tight text-foreground md:text-3xl">
            {title}
          </h1>
          {description && (
            <div className="mt-1.5 text-sm leading-relaxed text-muted-foreground">
              {description}
            </div>
          )}
        </div>
        {actions && (
          <div className="flex flex-wrap items-center gap-2">{actions}</div>
        )}
      </header>
      {meta && (
        <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2 text-xs text-muted-foreground">
          {meta}
        </div>
      )}
      {children && <div className="mt-6 space-y-6">{children}</div>}
    </div>
  );
}

interface AdminSectionProps {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}

export function AdminSection({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClassName,
}: AdminSectionProps) {
  return (
    <section
      className={`flex min-w-0 flex-col rounded-xl border border-border bg-surface-1 ${
        className ?? ''
      }`}
    >
      <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 px-5 pt-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">{title}</h2>
          {subtitle && (
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              {subtitle}
            </p>
          )}
        </div>
        {actions && <div className="shrink-0">{actions}</div>}
      </div>
      <div className={`min-w-0 flex-1 px-5 pb-5 pt-4 ${bodyClassName ?? ''}`}>
        {children}
      </div>
    </section>
  );
}

export function AdminPanel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`min-w-0 rounded-xl border border-border bg-surface-1 p-5 ${
        className ?? ''
      }`}
    >
      {children}
    </section>
  );
}

export function SectionHeading({
  title,
  description,
  actions,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-x-4 gap-y-2">
      <div className="min-w-0">
        <h2 className="admin-eyebrow">{title}</h2>
        {description && (
          <p className="mt-1 text-xs text-muted-foreground">{description}</p>
        )}
      </div>
      {actions && <div className="shrink-0">{actions}</div>}
    </div>
  );
}
