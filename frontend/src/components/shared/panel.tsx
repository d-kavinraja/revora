import { type ReactNode } from 'react';

/**
 * Flat content panel: hairline border, surface fill, xl radius (the one
 * radius for panels; controls use lg, hero media 2xl). Padding belongs to
 * the caller so dense and airy panels can share the frame.
 */
export function Panel({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-surface-1 ${className ?? ''}`}>
      {children}
    </section>
  );
}