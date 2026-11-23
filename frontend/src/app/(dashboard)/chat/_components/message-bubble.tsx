'use client';

import { useDeferredValue, useEffect, useMemo, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { CheckIcon, CopyIcon, RefreshCwIcon } from 'lucide-react';

import { cn } from '@/lib/utils';
import {
  computePrefillPercent,
  computeTokensPerSecond,
  type ChatMessage,
  type ResponseMetrics,
  type ResponsePhase,
} from '@/lib/chat-state';

interface MessageBubbleProps {
  message: ChatMessage;
  metrics?: ResponseMetrics;
  onRetry?: () => void;
  onRegenerate?: () => void;
  canRegenerate?: boolean;
}

const PHASE_LABEL: Record<ResponsePhase, string> = {
  preparing: 'Preparing context',
  thinking: 'Thinking',
  generating: 'Generating',
  complete: 'Complete',
  stopped: 'Generation stopped',
  error: 'Failed',
  truncated: 'Response truncated',
};

const PHASE_DOT: Record<ResponsePhase, string> = {
  preparing: 'bg-brand animate-pulse',
  thinking: 'bg-brand/80 animate-pulse',
  generating: 'bg-success animate-pulse',
  complete: 'bg-success',
  stopped: 'bg-warning',
  error: 'bg-error',
  truncated: 'bg-warning',
};

function formatElapsed(ms?: number): string | null {
  if (typeof ms !== 'number' || !Number.isFinite(ms) || ms < 0) return null;
  const seconds = ms / 1000;
  return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)}s`;
}

/** Compact live processing header: real telemetry only, no fabricated values. */
function ResponseProcessing({ metrics }: { metrics: ResponseMetrics }) {
  const active =
    metrics.phase === 'preparing' ||
    metrics.phase === 'thinking' ||
    metrics.phase === 'generating';
  const [now, setNow] = useState(() =>
    typeof performance !== 'undefined' ? performance.now() : 0,
  );

  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(performance.now()), 250);
    return () => window.clearInterval(id);
  }, [active]);

  const percent = computePrefillPercent(metrics.progress);
  const showProgress = active && metrics.phase === 'preparing' && percent !== null;
  const elapsed = formatElapsed(
    metrics.endedAt ?? (active && now >= metrics.startedAt ? now - metrics.startedAt : undefined),
  );
  const speed = metrics.genTps ?? computeTokensPerSecond(metrics.outputTokens, metrics.genMs);
  const contextPct =
    metrics.contextUsed !== undefined &&
    metrics.contextTotal !== undefined &&
    metrics.contextTotal > 0
      ? Math.min(100, Math.round((metrics.contextUsed / metrics.contextTotal) * 100))
      : null;

  return (
    <div className="mb-2.5 border-b border-border/50 pb-2">
      <div className="flex flex-col gap-1 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex min-w-0 items-center gap-1.5">
          <span
            aria-hidden
            className={cn('h-1.5 w-1.5 shrink-0 rounded-full', PHASE_DOT[metrics.phase])}
          />
          <span className="chat-ink text-xs font-medium">{PHASE_LABEL[metrics.phase]}</span>
          {metrics.model ? (
            <span className="chat-ink max-w-[160px] truncate text-[11px] opacity-80" title={metrics.model}>
              · {metrics.model}
            </span>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 text-xs tabular-nums text-muted-foreground sm:justify-end">
          {metrics.outputTokens !== undefined ? (
            <span>{metrics.outputTokens.toLocaleString()} tokens</span>
          ) : null}
          {speed !== null && Number.isFinite(speed) && speed > 0 ? (
            <>
              <span className="text-muted-foreground/50" aria-hidden>·</span>
              <span>{speed.toFixed(1)} tok/s</span>
            </>
          ) : null}
          {elapsed ? (
            <>
              <span className="text-muted-foreground/50" aria-hidden>·</span>
              <span>{elapsed}</span>
            </>
          ) : null}
          {contextPct !== null ? (
            <>
              <span className="text-muted-foreground/50" aria-hidden>·</span>
              <span>Context {contextPct}%</span>
            </>
          ) : null}
        </div>
      </div>
      {showProgress ? (
        <div
          className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-muted"
          role="progressbar"
          aria-valuenow={percent}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full rounded-full bg-brand transition-[width] duration-200"
            style={{ width: `${percent}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}

/** Extract raw text from React children (strings, arrays, elements). */
function extractText(node: React.ReactNode): string {
  if (typeof node === 'string') return node;
  if (typeof node === 'number') return String(node);
  if (Array.isArray(node)) return node.map(extractText).join('');
  if (node && typeof node === 'object' && 'props' in node) {
    const el = node as React.ReactElement<{ children?: React.ReactNode }>;
    return extractText(el.props.children);
  }
  return '';
}

/** Custom code block card with language header and copy button. */
function CodeBlock({ children }: { children: React.ReactNode }) {
  const [copied, setCopied] = useState(false);
  const codeEl = children as React.ReactElement<{ className?: string; children?: React.ReactNode }> | null;
  const className = codeEl?.props?.className || '';
  const langMatch = /language-(\w+)/.exec(className);
  const lang = langMatch ? langMatch[1] : 'code';
  const code = extractText(codeEl?.props?.children);

  const handleCopy = async () => {
    if (typeof navigator === 'undefined') return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(code);
      } else {
        const ta = document.createElement('textarea');
        ta.value = code;
        ta.style.position = 'fixed';
        ta.style.left = '-9999px';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore clipboard errors
    }
  };

  return (
    <div className="my-3 overflow-hidden rounded-xl border border-white/10 bg-[#0f172a]">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-1.5">
        <span className="text-[11px] font-medium text-slate-400">{lang}</span>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1 text-[11px] text-slate-400 transition hover:text-slate-200"
          aria-label={copied ? 'Copied' : 'Copy code'}
        >
          {copied ? <CheckIcon size={12} className="text-emerald-400" /> : <CopyIcon size={12} />}
          <span>{copied ? 'Copied!' : 'Copy'}</span>
        </button>
      </div>
      <pre className="!m-0 !border-0 !rounded-none overflow-x-auto p-3 text-[13px] leading-6 text-[#f8fafc]">
        <code className={className}>{codeEl?.props?.children}</code>
      </pre>
    </div>
  );
}

export function MessageBubble({ message, metrics, onRetry, onRegenerate, canRegenerate }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false);
  const isUser = message.role === 'user';
  const isError = message.status === 'error';
  const isStreaming = message.status === 'streaming';
  const hasContent = !!message.content?.trim();

  // The same renderer is used for streaming and completed assistant messages:
  // markdown is parsed as soon as its syntax is complete, with no end-of-stream
  // swap. Deferring the source lets React coalesce parses under load, and the
  // memo keeps telemetry-only re-renders from reparsing unchanged content.
  const markdownSource = message.content || (isError ? 'Response failed.' : '');
  const deferredMarkdown = useDeferredValue(markdownSource);
  const renderedMarkdown = useMemo(
    () => (
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{ pre: ({ children }) => <CodeBlock>{children}</CodeBlock> }}
      >
        {deferredMarkdown}
      </ReactMarkdown>
    ),
    [deferredMarkdown],
  );

  const handleCopy = async () => {
    if (!hasContent || typeof navigator === 'undefined') return;
    try {
      await navigator.clipboard.writeText(message.content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // ignore
    }
  };

  return (
    <div className={`group/msg flex ${isUser ? 'justify-end' : 'justify-start'}`}>
      <div className={`min-w-0 ${isUser ? 'max-w-[92%] md:max-w-[78%]' : 'w-full max-w-[92%] md:max-w-[100%]'}`}>
        <div
          className={`text-[15px] leading-7 ${
            isUser
              ? 'rounded-2xl rounded-br-sm border border-slate-800 bg-slate-900 px-4 py-3 text-white shadow-sm dark:border-slate-200/80 dark:bg-slate-100 dark:text-slate-900'
              : isError
                ? 'rounded-2xl border border-slate-200/90 bg-white/95 px-4 py-3 text-slate-900 shadow-sm backdrop-blur-md ring-1 ring-error/20 dark:border-white/10 dark:bg-zinc-900/85 dark:text-slate-100'
                : 'rounded-2xl border border-slate-200/90 bg-white/95 px-4 py-3 text-slate-900 shadow-sm backdrop-blur-md dark:border-white/10 dark:bg-zinc-900/85 dark:text-slate-100'
          }`}
        >
          {!isUser && metrics ? <ResponseProcessing metrics={metrics} /> : null}
          {isUser ? (
            <p className="whitespace-pre-wrap break-words">{message.content}</p>
          ) : isStreaming && !hasContent ? (
            <div className="whitespace-pre-wrap break-words text-foreground/95">
              {!metrics ? <span className="chat-ink">Thinking...</span> : null}
              <span className="ml-1 inline-block h-4 w-1.5 animate-pulse rounded-sm bg-foreground/40 align-middle" />
            </div>
          ) : (
            <div className="chat-markdown prose prose-sm dark:prose-invert max-w-none prose-p:my-0 prose-p:leading-7 prose-li:my-0 prose-pre:my-3 prose-pre:overflow-x-auto prose-pre:rounded-xl prose-code:before:content-none prose-code:after:content-none">
              {renderedMarkdown}
            </div>
          )}

          {message.status === 'stopped' && !isUser && (
            <p className="chat-ink mt-2 text-xs">Generation stopped</p>
          )}

          {isError && !isUser && (
            <div className="mt-3 flex flex-wrap items-center gap-3">
              <p className="text-xs text-error">{message.error || 'The model could not complete this response.'}</p>
              {onRetry && (
                <button
                  type="button"
                  onClick={onRetry}
                  className="inline-flex items-center gap-1.5 rounded-md border border-border/80 px-2.5 py-1 text-xs text-foreground transition hover:bg-muted/60"
                >
                  <RefreshCwIcon size={12} />
                  Retry
                </button>
              )}
            </div>
          )}
        </div>

        {!isStreaming && !isError && hasContent ? (
          <div className={`mt-1 flex items-center gap-1 ${isUser ? 'justify-end opacity-0 transition-opacity group-hover/msg:opacity-100 group-focus-within/msg:opacity-100' : 'justify-start'}`}>
            <button
              type="button"
              onClick={handleCopy}
              className="chat-ink inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs transition hover:bg-muted/60 hover:text-foreground"
              aria-label={copied ? 'Copied' : 'Copy message'}
              title={copied ? 'Copied' : 'Copy'}
            >
              {copied ? <CheckIcon size={13} /> : <CopyIcon size={13} />}
              <span className="sr-only sm:not-sr-only">{copied ? 'Copied' : 'Copy'}</span>
            </button>
            {!isUser && onRegenerate ? (
              <button
                type="button"
                onClick={onRegenerate}
                disabled={!canRegenerate}
                className="chat-ink inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-xs transition hover:bg-muted/60 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
                aria-label="Regenerate response"
                title="Regenerate"
              >
                <RefreshCwIcon size={13} />
                <span className="sr-only sm:not-sr-only">Regenerate</span>
              </button>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}