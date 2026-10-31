'use client';

import { type ReactNode } from 'react';
import { Modal } from '@/components/shared/modal';

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'danger' | 'default';
  busy?: boolean;
  confirmDisabled?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  /** Optional body (e.g. a required reason textarea). */
  children?: ReactNode;
}

/**
 * Confirmation dialog built on the shared accessible modal: Esc cancels,
 * focus is trapped and restored, and every target is at least 44 px.
 */
export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  tone = 'default',
  busy = false,
  confirmDisabled = false,
  onConfirm,
  onCancel,
  children,
}: ConfirmDialogProps) {
  const confirmCls =
    tone === 'danger'
      ? 'border-transparent bg-error text-white hover:opacity-90'
      : 'border-transparent bg-brand text-brand-foreground hover:bg-brand-hover';

  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      description={description}
      busy={busy}
      footer={
        <>
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="h-11 cursor-pointer rounded-lg border border-border px-4 text-sm font-medium text-foreground/80 transition-colors hover:bg-surface-2 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 disabled:opacity-40"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || confirmDisabled}
            className={`h-11 cursor-pointer rounded-lg border px-4 text-sm font-semibold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1 disabled:cursor-not-allowed disabled:opacity-40 ${confirmCls}`}
          >
            {busy ? 'Working…' : confirmLabel}
          </button>
        </>
      }
    >
      {children}
    </Modal>
  );
}
