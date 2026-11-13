'use client';

import { useCallback, useState } from 'react';
import { Check, Copy } from 'lucide-react';

async function copyText(value: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', '');
  textarea.style.position = 'fixed';
  textarea.style.opacity = '0';
  document.body.appendChild(textarea);
  textarea.select();
  document.execCommand('copy');
  document.body.removeChild(textarea);
}

export function CopyButton({
  value,
  label = 'Copy',
  copiedLabel = 'Copied',
  className = '',
  iconOnly = false,
}: {
  value: string;
  label?: string;
  copiedLabel?: string;
  className?: string;
  iconOnly?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await copyText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  }, [value]);

  return (
    <button
      type="button"
      onClick={handleCopy}
      className={`inline-flex h-11 cursor-pointer items-center justify-center gap-2 rounded-lg border border-border bg-surface-2 px-3 text-xs font-medium text-foreground/80 transition-colors hover:bg-surface-3 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand focus-visible:ring-offset-2 focus-visible:ring-offset-background ${
        iconOnly ? 'w-11 px-0' : ''
      } ${className}`}
      aria-label={copied ? copiedLabel : label}
      title={copied ? copiedLabel : label}
    >
      {copied ? (
        <Check size={15} className="shrink-0 text-success" aria-hidden="true" />
      ) : (
        <Copy size={15} className="shrink-0" aria-hidden="true" />
      )}
      {!iconOnly && <span>{copied ? copiedLabel : label}</span>}
    </button>
  );
}
