'use client';

import { useEffect, useId, useRef, type ReactNode } from 'react';
import { X } from 'lucide-react';

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

interface SlideOverProps {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  /** Extra actions rendered in the header (e.g. Previous/Next navigation). */
  headerActions?: ReactNode;
  footer?: ReactNode;
  /** Tailwind max-width utility for the desktop drawer panel. */
  width?: string;
}

/**
 * Accessible right-side drawer.
 *
 * Desktop: fixed right-hand panel that leaves the underlying page visible
 * behind a translucent backdrop. Mobile: full-screen details view.
 * Focus is trapped while open, Escape closes, background scrolling is locked,
 * and focus is restored to the trigger on close.
 */
export function SlideOver({
  open,
  onClose,
  title,
  description,
  children,
  headerActions,
  footer,
  width = 'md:max-w-xl',
}: SlideOverProps) {
  const panelRef = useRef<HTMLDivElement>(null);
  const onCloseRef = useRef(onClose);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    onCloseRef.current = onClose;
  });

  useEffect(() => {
    if (!open) return;

    const previousFocus =
      document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const focusFirst = () => {
      const panel = panelRef.current;
      if (!panel) return;
      const targets = panel.querySelectorAll<HTMLElement>(FOCUSABLE);
      (targets[0] ?? panel).focus();
    };
    focusFirst();

    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab') return;
      const panel = panelRef.current;
      if (!panel) return;
      const targets = Array.from(
        panel.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter((element) => element.offsetParent !== null);
      if (targets.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = targets[0];
      const last = targets[targets.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && (active === first || active === panel)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first.focus();
      }
    };

    window.addEventListener('keydown', handleKey);
    return () => {
      window.removeEventListener('keydown', handleKey);
      document.body.style.overflow = previousOverflow;
      previousFocus?.focus();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-[2px]"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={description ? descriptionId : undefined}
        tabIndex={-1}
        className={`admin-motion absolute inset-0 flex w-full flex-col bg-surface-1 shadow-2xl focus:outline-none md:inset-y-0 md:left-auto md:right-0 md:w-full md:max-h-none md:border-l md:border-border ${width}`}
      >
        <div className="flex h-16 shrink-0 items-start justify-between gap-3 border-b border-border px-4 sm:px-5">
          <div className="min-w-0 flex-1 pt-3">
            <h2
              id={titleId}
              className="truncate text-base font-semibold text-foreground"
            >
              {title}
            </h2>
            {description && (
              <div
                id={descriptionId}
                className="mt-0.5 truncate text-xs text-muted-foreground"
              >
                {description}
              </div>
            )}
          </div>
          {headerActions && (
            <div className="flex shrink-0 items-center gap-2 pt-3">{headerActions}</div>
          )}
          <button
            type="button"
            onClick={onClose}
            aria-label="Close details"
            className="inline-flex h-11 w-11 shrink-0 cursor-pointer items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand"
          >
            <X size={17} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 sm:px-5 sm:py-5">
          {children}
        </div>

        {footer && (
          <div className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-border px-4 py-3 sm:px-5">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}
