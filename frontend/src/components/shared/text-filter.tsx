'use client';

import { useEffect, useState } from 'react';
import { Search } from 'lucide-react';

interface TextFilterProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel: string;
  className?: string;
  debounceMs?: number;
}

/**
 * Debounced text filter. Keeps a local buffer while typing and only lifts
 * the value after `debounceMs`. When the parent resets `value` externally,
 * the buffer re-syncs using the render-time state-adjustment pattern
 * (https://react.dev/learn/you-might-not-need-an-effect).
 */
export function TextFilter({
  value,
  onChange,
  placeholder,
  ariaLabel,
  className,
  debounceMs = 300,
}: TextFilterProps) {
  const [local, setLocal] = useState(value);
  const [lastValue, setLastValue] = useState(value);

  if (value !== lastValue) {
    setLastValue(value);
    setLocal(value);
  }

  useEffect(() => {
    if (local === value) return;
    const timer = setTimeout(() => onChange(local.trim()), debounceMs);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [local, debounceMs]);

  return (
    <div className={`relative min-w-0 ${className ?? ''}`}>
      <Search
        size={15}
        className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground"
        aria-hidden="true"
      />
      <input
        type="search"
        value={local}
        onChange={(event) => setLocal(event.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className="h-11 w-full rounded-lg border border-border bg-surface-1 pl-9 pr-3 text-sm text-foreground placeholder:text-muted-foreground transition-colors hover:border-[var(--admin-hairline-strong)] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
      />
    </div>
  );
}
