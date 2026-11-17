'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { MoreVertical } from 'lucide-react';
import { REVORA } from '@/lib/site';

const ITEMS = [
  { label: 'Setup', href: '/#setup' },
  { label: 'Docs', href: REVORA.github.readme },
  { label: 'Install', href: REVORA.github.app },
  { label: 'Sign In', href: '/login' },
  { label: 'Get Started', href: '/register' },
] as const;

export function AuthMobileMenu() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const close = () => setOpen(false);
    queueMicrotask(close);
    return () => {};
  }, [pathname]);

  useEffect(() => {
    if (!open) return;

    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };

    const onPointer = (event: PointerEvent) => {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };

    document.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onPointer);
    containerRef.current
      ?.querySelector<HTMLAnchorElement>('[role="menuitem"]')
      ?.focus();

    return () => {
      document.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onPointer);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={open ? 'Close navigation menu' : 'Open navigation menu'}
        onClick={() => setOpen((value) => !value)}
        className="inline-flex size-10 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-white/[0.06] hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        <MoreVertical className="size-5" aria-hidden="true" />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Navigation options"
          className="absolute right-0 top-full z-50 mt-2 min-w-[190px] rounded-xl border border-border bg-background/95 p-1.5 shadow-xl backdrop-blur-md"
        >
          {ITEMS.map((item) => {
            const active = pathname === item.href;

            return (
              <Link
                key={item.label}
                role="menuitem"
                href={item.href}
                onClick={() => setOpen(false)}
                aria-current={active ? 'page' : undefined}
                className="flex min-h-11 items-center rounded-lg px-3 text-sm font-medium text-foreground transition-colors hover:bg-muted aria-[current=page]:bg-muted"
              >
                {item.label}
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
