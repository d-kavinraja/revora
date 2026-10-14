'use client';

import { useState } from 'react';
import { Check, Copy, FileJson } from 'lucide-react';
import { useToast } from '@/components/ui/toaster';

interface JsonViewerProps {
  title?: string;
  subtitle?: string;
  data: unknown | null;
  emptyText?: string;
  className?: string;
}

export function JsonViewer({ title, subtitle, data, emptyText, className }: JsonViewerProps) {
  const { toast } = useToast();
  const [copied, setCopied] = useState(false);
  const text = data ? JSON.stringify(data, null, 2) : null;

  const copy = async () => {
    if (!text) return;
    try {
      await navigator.clipboard.writeText(text);
    } catch {
      const ta = document.createElement('textarea');
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand('copy');
      document.body.removeChild(ta);
    }
    setCopied(true);
    toast({ title: 'Copied', description: 'Inference response copied to clipboard.', type: 'success' });
    window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div
      className={`rounded-xl border border-border bg-surface-1 flex flex-col ${className ?? ''}`}
    >
      <div className="flex items-center gap-2 px-4 pt-4 shrink-0">
        <span className="w-8 h-8 rounded-lg bg-ai-purple/10 text-ai-purple flex items-center justify-center shrink-0">
          <FileJson size={20} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-xl font-semibold truncate leading-tight">
            {title ?? 'Inference Output'}
          </p>
          {subtitle ? (
            <p className="text-xs text-foreground/65 leading-snug truncate">
              {subtitle}
            </p>
          ) : null}
        </div>
        <button
          onClick={copy}
          disabled={!text}
          className="inline-flex items-center gap-1 px-3 min-h-[40px] rounded-lg text-xs font-medium border border-brand/40 text-brand hover:bg-brand/10 disabled:opacity-40 transition-colors"
          aria-label="Copy inference response JSON"
        >
          {copied ? <Check size={13} className="text-success" /> : <Copy size={13} />}
          Copy
        </button>
      </div>
      <div className="p-4 flex-1 min-h-0">
        {text ? (
          <pre className="text-xs font-mono rounded-lg bg-surface-2 p-3 overflow-auto max-h-[240px] h-full whitespace-pre">
            {text}
          </pre>
        ) : (
          <p className="text-xs text-foreground/70 rounded-lg bg-surface-2 p-3 leading-relaxed h-full">
            {emptyText ?? 'No inference response yet.'}
          </p>
        )}
      </div>
    </div>
  );
}
