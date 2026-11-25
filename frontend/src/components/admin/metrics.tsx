'use client';

import { type ReactNode, useId } from 'react';
import { motion, useReducedMotion } from 'motion/react';

export type MeterTone =
  | 'brand'
  | 'success'
  | 'warning'
  | 'error'
  | 'info'
  | 'muted';

const TONE_FILL: Record<MeterTone, string> = {
  brand: 'bg-brand',
  success: 'bg-success',
  warning: 'bg-warning',
  error: 'bg-error',
  info: 'bg-info',
  muted: 'bg-muted-foreground/60',
};

interface KpiTileProps {
  label: string;
  value: string;
  sub?: ReactNode;
  reason?: string | null;
  unavailable?: boolean;
  icon?: ReactNode;
  tone?: MeterTone;
}

export function KpiTile({
  label,
  value,
  sub,
  reason,
  unavailable = false,
  icon,
  tone = 'brand',
}: KpiTileProps) {
  return (
    <article className="relative min-w-0 overflow-hidden rounded-xl border border-border bg-surface-1 p-4">
      <span
        aria-hidden="true"
        className={`absolute inset-x-4 top-0 h-0.5 rounded-b ${
          unavailable
            ? 'admin-unrecorded'
            : tone === 'brand'
              ? 'bg-gradient-to-r from-brand to-transparent'
              : TONE_FILL[tone]
        }`}
      />
      <div className="flex items-start justify-between gap-3">
        <p className="admin-label min-w-0 truncate">{label}</p>
        {icon && (
          <span className="shrink-0 text-muted-foreground" aria-hidden="true">
            {icon}
          </span>
        )}
      </div>
      <p
        className={`admin-readout mt-2 text-2xl font-semibold ${
          unavailable ? 'text-muted-foreground' : 'text-foreground'
        }`}
      >
        {value}
      </p>
      {sub && (
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {sub}
        </p>
      )}
      {reason && (
        <p className="mt-1 font-mono text-[11px] leading-relaxed text-muted-foreground">
          {reason}
        </p>
      )}
    </article>
  );
}

export function StatGroup({
  label,
  description,
  children,
  columns = 4,
}: {
  label: string;
  description?: ReactNode;
  children: ReactNode;
  columns?: 2 | 3 | 4;
}) {
  const cols =
    columns === 2
      ? 'sm:grid-cols-2'
      : columns === 3
        ? 'sm:grid-cols-2 xl:grid-cols-3'
        : 'sm:grid-cols-2 xl:grid-cols-4';
  return (
    <section aria-label={label}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="admin-label font-semibold text-foreground">{label}</h2>
        {description && (
          <p className="text-xs text-muted-foreground">{description}</p>
        )}
      </div>
      <div className={`mt-3 grid gap-3 ${cols}`}>{children}</div>
    </section>
  );
}

export function MeterRow({
  label,
  secondary,
  value,
  max,
  tone = 'brand',
  leading,
}: {
  label: string;
  secondary?: string | null;
  value: number;
  max: number;
  tone?: MeterTone;
  leading?: ReactNode;
}) {
  const pct = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return (
    <div className="min-w-0">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="flex min-w-0 items-baseline gap-2 text-foreground/85" title={label}>
          {leading}
          <span className="min-w-0">
            <span className="block truncate">{label}</span>
            {secondary && (
              <span className="block truncate text-xs text-muted-foreground">
                {secondary}
              </span>
            )}
          </span>
        </span>
        <span className="admin-figure shrink-0 font-semibold text-foreground">
          {value.toLocaleString()}
        </span>
      </div>
      <div
        className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-surface-2"
        role="img"
        aria-label={`${label}: ${value.toLocaleString()} of ${max.toLocaleString()}`}
      >
        <div
          className={`h-full rounded-full ${TONE_FILL[tone]}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

export interface RankedItem {
  key: string;
  label: string;
  secondary?: string | null;
  value: number;
  tone?: MeterTone;
  leading?: ReactNode;
}

export function RankedList({
  items,
  tone = 'brand',
}: {
  items: RankedItem[];
  tone?: MeterTone;
}) {
  const max = items.reduce((peak, item) => Math.max(peak, item.value), 0);
  return (
    <ul className="space-y-3">
      {items.map((item) => (
        <li key={item.key}>
          <MeterRow
            label={item.label}
            secondary={item.secondary}
            value={item.value}
            max={max}
            tone={item.tone ?? tone}
            leading={item.leading}
          />
        </li>
      ))}
    </ul>
  );
}

export interface DistributionItem {
  key: string;
  label: string;
  value: number;
  tone: MeterTone;
}

export function DistributionBar({ items }: { items: DistributionItem[] }) {
  const total = items.reduce((sum, item) => sum + item.value, 0);
  if (total === 0) return null;

  return (
    <div>
      <div
        className="flex h-2 w-full overflow-hidden rounded-full bg-surface-2"
        role="img"
        aria-label={items
          .map((item) => `${item.label}: ${item.value.toLocaleString()}`)
          .join('; ')}
      >
        {items.map((item) => (
          <span
            key={item.key}
            className={TONE_FILL[item.tone]}
            style={{ width: `${(item.value / total) * 100}%` }}
          />
        ))}
      </div>
      <ul className="mt-4 grid gap-x-6 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
        {items.map((item) => (
          <li
            key={item.key}
            className="flex min-w-0 items-center justify-between gap-3 text-sm"
          >
            <span className="flex min-w-0 items-center gap-2">
              <span
                aria-hidden="true"
                className={`h-2 w-2 shrink-0 rounded-full ${TONE_FILL[item.tone]}`}
              />
              <span className="truncate capitalize text-foreground/80">
                {item.label}
              </span>
            </span>
            <span className="admin-figure shrink-0 font-semibold text-foreground">
              {item.value.toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Hero band: one verdict, its readouts, and the page's controls. The single
 * memorable surface on a page — everything else stays quiet around it.
 */
export interface RibbonReadout {
  key: string;
  label: string;
  value: string;
  sub?: string | null;
}

export function StatusRibbon({
  label,
  verdict,
  hint,
  readouts = [],
  actions,
}: {
  label: string;
  verdict: ReactNode;
  hint?: ReactNode;
  readouts?: RibbonReadout[];
  actions?: ReactNode;
}) {
  const reduceMotion = useReducedMotion();

  return (
    <motion.section
      aria-label={label}
      initial={reduceMotion ? false : { opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, ease: 'easeOut' }}
      className="admin-hero admin-tick flex flex-col gap-5 p-5 lg:flex-row lg:items-center lg:gap-8"
    >
      <div className="min-w-0 lg:max-w-xs">
        <p className="admin-label">{label}</p>
        <p className="admin-readout mt-1.5 text-xl font-semibold text-foreground">
          {verdict}
        </p>
        {hint && (
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            {hint}
          </p>
        )}
      </div>

      {readouts.length > 0 && (
        <div className="grid min-w-0 flex-1 grid-cols-2 gap-x-8 gap-y-4 border-border sm:grid-cols-3 lg:border-l lg:pl-8 xl:grid-cols-4">
          {readouts.map((readout) => (
            <div key={readout.key} className="min-w-0">
              <p className="admin-label truncate">{readout.label}</p>
              <p className="admin-readout mt-1 truncate text-lg font-semibold text-foreground">
                {readout.value}
              </p>
              {readout.sub && (
                <p className="mt-0.5 truncate text-xs text-muted-foreground">
                  {readout.sub}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {actions && (
        <div className="flex shrink-0 flex-wrap items-center gap-2 lg:ml-auto">
          {actions}
        </div>
      )}
    </motion.section>
  );
}

export function SegmentedControl({
  options,
  value,
  onChange,
  ariaLabel,
}: {
  options: ReadonlyArray<{ key: string; label: string }>;
  value: string;
  onChange: (key: string) => void;
  ariaLabel: string;
}) {
  const layoutId = useId();
  const reduceMotion = useReducedMotion();

  return (
    <div
      role="group"
      aria-label={ariaLabel}
      className="inline-flex h-11 items-center rounded-lg border border-border bg-surface-1 p-1"
    >
      {options.map((option) => {
        const active = option.key === value;
        return (
          <button
            key={option.key}
            type="button"
            onClick={() => onChange(option.key)}
            aria-pressed={active}
            className={`relative h-9 cursor-pointer rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand ${
              active
                ? 'text-brand'
                : 'text-foreground/70 hover:bg-surface-2 hover:text-foreground'
            }`}
          >
            {active && (
              <motion.span
                layoutId={reduceMotion ? undefined : layoutId}
                className="absolute inset-0 rounded-md border border-brand/30 bg-brand/10"
                transition={{ duration: 0.18, ease: 'easeOut' }}
              />
            )}
            <span className="relative">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}
