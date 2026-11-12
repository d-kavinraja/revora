import Link from 'next/link';
import { Construction, Hourglass, Rocket, Wrench } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

const STATUS_META: Record<
  string,
  { label: string; description: string; Icon: LucideIcon }
> = {
  disabled: {
    label: 'Temporarily unavailable',
    description:
      'This feature is temporarily unavailable. Please try again later.',
    Icon: Construction,
  },
  maintenance: {
    label: 'Under maintenance',
    description:
      'This feature is under maintenance. Please try again later.',
    Icon: Wrench,
  },
  coming_soon: {
    label: 'Coming soon',
    description: 'This feature is coming soon.',
    Icon: Rocket,
  },
  under_testing: {
    label: 'Under testing',
    description: 'This feature is under testing and will be available soon.',
    Icon: Hourglass,
  },
};

interface FeatureUnavailableProps {
  /** Flag status from `/platform/features` (defaults to `disabled`). */
  status?: string | null;
  /** Admin-configured message; falls back to per-status copy. */
  message?: string | null;
  /** Optional title override. */
  title?: string;
  className?: string;
  /** `page` renders a full-page state inside the dashboard shell. */
  variant?: 'card' | 'page';
}

/**
 * Shared cosmetic gate for flag-disabled pages (§11.1). Server-side
 * enforcement is the real block — this only explains the state to users.
 */
export function FeatureUnavailable({
  status,
  message,
  title,
  className = '',
  variant = 'card',
}: FeatureUnavailableProps) {
  const meta = STATUS_META[status ?? 'disabled'] ?? STATUS_META.disabled;
  const Icon = meta.Icon;

  if (variant === 'page') {
    return (
      <div
        role="status"
        className={`mx-auto flex min-h-[50vh] w-full max-w-[720px] flex-col items-center justify-center gap-4 px-4 py-16 text-center ${className}`}
      >
        <div className="flex h-16 w-16 items-center justify-center rounded-full border border-border bg-surface-2 text-muted-foreground">
          <Icon size={28} aria-hidden="true" />
        </div>
        <div className="space-y-2">
          <p className="text-lg font-semibold text-foreground">{title ?? meta.label}</p>
          <p className="mx-auto max-w-md text-sm leading-relaxed text-muted-foreground">
            {message || meta.description}
          </p>
        </div>
        <Link
          href="/dashboard"
          className="text-sm font-medium text-brand hover:text-brand-hover"
        >
          Back to dashboard
        </Link>
      </div>
    );
  }

  return (
    <div
      role="status"
      className={`rounded-xl border border-border bg-surface-1 p-10 text-center ${className}`}
    >
      <div className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon size={24} aria-hidden="true" />
      </div>
      <p className="mt-4 font-medium text-foreground">{title ?? meta.label}</p>
      <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
        {message || meta.description}
      </p>
    </div>
  );
}
