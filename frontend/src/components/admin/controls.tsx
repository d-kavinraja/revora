import {
  type ButtonHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react';
import { ChevronDown } from 'lucide-react';

export const ADMIN_INPUT_CLASS =
  'h-11 w-full rounded-lg border border-border bg-surface-1 px-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors hover:border-border focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-60';

export const ADMIN_TEXTAREA_CLASS =
  'w-full rounded-lg border border-border bg-surface-1 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed disabled:opacity-60';

export const ADMIN_LABEL_CLASS =
  'mb-1 block text-xs font-medium text-muted-foreground';

export function FilterBar({
  children,
  actions,
  label,
}: {
  children: ReactNode;
  actions?: ReactNode;
  label?: string;
}) {
  return (
    <div
      role="group"
      aria-label={label}
      className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface-1 p-3"
    >
      {children}
      {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function SelectFilter({
  label,
  className,
  children,
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string;
  className?: string;
}) {
  return (
    <div className={`relative min-w-0 ${className ?? ''}`}>
      <select
        {...props}
        className={`${ADMIN_INPUT_CLASS} cursor-pointer appearance-none pr-9`}
      >
        {children}
      </select>
      <ChevronDown
        size={15}
        aria-hidden="true"
        className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-muted-foreground"
      />
      {label && <span className="sr-only">{label}</span>}
    </div>
  );
}

export function Field({
  label,
  htmlFor,
  hint,
  children,
  className,
}: {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`min-w-0 ${className ?? ''}`}>
      <label htmlFor={htmlFor} className={ADMIN_LABEL_CLASS}>
        {label}
      </label>
      {children}
      {hint && (
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

export function CheckboxRow({
  checked,
  onChange,
  title,
  description,
  disabled,
}: {
  checked: boolean;
  onChange: (next: boolean) => void;
  title: string;
  description?: ReactNode;
  disabled?: boolean;
}) {
  return (
    <label className="flex min-h-11 cursor-pointer items-start gap-3 py-1">
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 h-4 w-4 shrink-0 cursor-pointer rounded border-border accent-brand focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand disabled:cursor-not-allowed"
      />
      <span className="min-w-0">
        <span className="block text-sm text-foreground">{title}</span>
        {description && (
          <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
            {description}
          </span>
        )}
      </span>
    </label>
  );
}

type ButtonVariant =
  | 'primary'
  | 'secondary'
  | 'ghost'
  | 'danger'
  | 'dangerSoft'
  | 'successSoft';

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'border-transparent bg-brand text-brand-foreground hover:bg-brand-hover',
  secondary:
    'border-border bg-surface-2 text-foreground hover:bg-surface-3 hover:border-[var(--admin-hairline-strong)]',
  ghost:
    'border-transparent bg-transparent text-foreground/75 hover:bg-surface-2 hover:text-foreground',
  danger: 'border-transparent bg-error text-white hover:opacity-90',
  dangerSoft: 'border-error/30 bg-error/10 text-error hover:bg-error/20',
  successSoft:
    'border-success/30 bg-success/10 text-success hover:bg-success/20',
};

export function AdminButton({
  variant = 'secondary',
  size = 'md',
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: 'md' | 'sm';
}) {
  return (
    <button
      {...props}
      type={props.type ?? 'button'}
      className={`inline-flex cursor-pointer items-center justify-center gap-2 rounded-lg border font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 ${
        size === 'sm' ? 'h-9 px-3 text-xs' : 'h-11 px-4 text-sm'
      } ${BUTTON_VARIANTS[variant]} ${className ?? ''}`}
    >
      {children}
    </button>
  );
}

export function IconButton({
  label,
  className,
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { label: string }) {
  return (
    <button
      {...props}
      type={props.type ?? 'button'}
      aria-label={label}
      title={label}
      className={`inline-flex h-11 w-11 cursor-pointer items-center justify-center rounded-lg border border-border text-foreground/70 transition-colors hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-background disabled:cursor-not-allowed disabled:opacity-50 ${
        className ?? ''
      }`}
    >
      {children}
    </button>
  );
}
