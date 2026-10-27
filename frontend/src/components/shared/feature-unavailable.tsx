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
}: FeatureUnavailableProps) {
  const meta = STATUS_META[status ?? 'disabled'] ?? STATUS_META.disabled;
  const Icon = meta.Icon;
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
