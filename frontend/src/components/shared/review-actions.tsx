'use client';

import { Repeat, ArrowUpDown, Play, Ban } from 'lucide-react';
import { LoaderIcon } from '@/components/ui/loader-icon';
import type { Review, ReviewStatus } from '@/lib/api';

interface ReviewActionsProps {
  review: Pick<Review, 'id' | 'status' | 'github_pr_state' | 'pr_has_active_review'>;
  onAction: (reviewId: string, action: string) => void;
  isActioning?: boolean;
  actioningAction?: string | null;
  variant?: 'compact' | 'full';
}

type ActionDef = {
  label: string;
  icon: React.ReactNode;
  action: string;
  color: string;
  fullClass: string;
  desc: string;
};

const inFlightLabels: Record<string, string> = {
  rerun: 'Rerunning…',
  retry: 'Retrying…',
  restart: 'Restarting…',
  cancel: 'Cancelling…',
};

// Strict status→action matrix: active reviews only expose Cancel, and each
// terminal status exposes exactly one recovery action — Rerun (completed),
// Retry (failed/timed_out), Restart (stopped/cancelled). This prevents
// duplicate executions for the same PR while active.
function getApplicableActions(status: ReviewStatus): ActionDef[] {
  switch (status) {
    case 'queued':
    case 'pending':
    case 'running':
      return [
        { label: 'Cancel', icon: <Ban size={12} />, action: 'cancel', color: 'text-error hover:bg-error/10', fullClass: 'bg-error/10 hover:bg-error/20 text-error border-error/20', desc: 'Stop this review immediately' },
      ];
    case 'completed':
      return [{ label: 'Rerun', icon: <Repeat size={12} />, action: 'rerun', color: 'text-brand hover:bg-brand/10', fullClass: 'bg-brand/10 hover:bg-brand/20 text-brand border-brand/20', desc: 'Run a new review of this PR (same row is reused)' }];
    case 'failed':
      return [{ label: 'Retry', icon: <ArrowUpDown size={12} />, action: 'retry', color: 'text-warning hover:bg-warning/10', fullClass: 'bg-warning/10 hover:bg-warning/20 text-warning border-warning/20', desc: 'Retry the review with current repository config' }];
    case 'timed_out':
      return [{ label: 'Retry', icon: <ArrowUpDown size={12} />, action: 'retry', color: 'text-warning hover:bg-warning/10', fullClass: 'bg-warning/10 hover:bg-warning/20 text-warning border-warning/20', desc: 'Retry the review after timeout' }];
    case 'stopped':
    case 'cancelled':
      return [{ label: 'Restart', icon: <Play size={12} />, action: 'restart', color: 'text-info hover:bg-info/10', fullClass: 'bg-info/10 hover:bg-info/20 text-info border-info/20', desc: 'Restart the review from the beginning' }];
    default:
      return [];
  }
}

function prBlockedTooltip(github_pr_state: string): string | null {
  if (github_pr_state === 'open' || github_pr_state === 'unknown') return null;
  if (github_pr_state === 'closed') return 'PR is closed — only cancel is available';
  if (github_pr_state === 'merged') return 'PR is merged — only cancel is available';
  return `PR is ${github_pr_state} — only cancel is available`;
}

const activeReviewTooltip = 'Another review for this pull request is already in progress.';

export function ReviewActions({ review, onAction, isActioning = false, actioningAction = null, variant = 'full' }: ReviewActionsProps) {
  const actions = getApplicableActions(review.status);
  const prBlocked = review.github_pr_state !== 'open' && review.github_pr_state !== 'unknown';
  const prBlockedByActive = review.pr_has_active_review === true;
  const tooltip = prBlocked ? prBlockedTooltip(review.github_pr_state) : prBlockedByActive ? activeReviewTooltip : null;

  if (actions.length === 0) return null;

  const renderButton = (label: string, icon: React.ReactNode, action: string, color: string, fullClass: string, desc: string, compact: boolean) => {
    const isCancel = action === 'cancel';
    const isInFlight = isActioning && actioningAction === action;
    const disabled = (!isCancel && (prBlocked || prBlockedByActive)) || isActioning;
    const finalLabel = isInFlight ? inFlightLabels[action] ?? label : label;
    const title = disabled && !isCancel && tooltip ? tooltip : desc;
    const size = compact ? 12 : 14;
    return (
      <button
        key={action}
        onClick={() => onAction(review.id, action)}
        disabled={disabled}
        title={title}
        className={
          compact
            ? `flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium transition-colors cursor-pointer ${color} disabled:opacity-50 disabled:cursor-not-allowed`
            : `flex items-center gap-2 px-3 py-2 rounded-lg text-xs font-semibold transition-colors border cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed ${fullClass}`
        }
      >
        {isInFlight ? <LoaderIcon size={size} animate /> : icon}
        {finalLabel}
      </button>
    );
  };

  if (variant === 'compact') {
    return (
      <div className="flex items-center gap-1 ml-auto">
        {actions.map(({ label, icon, action, color, fullClass }) =>
          renderButton(label, icon, action, color, fullClass, action === 'cancel' ? 'Stop this review immediately' : '', true)
        )}
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-border bg-surface-1 p-4 mb-5">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">Lifecycle Actions</span>
        {tooltip && (
          <span className="text-[10px] text-error/80 font-medium ml-auto">{tooltip}</span>
        )}
      </div>
      <div className="flex flex-wrap gap-2">
        {actions.map(({ label, icon, action, color, fullClass, desc }) =>
          renderButton(label, icon, action, color, fullClass, desc, false)
        )}
      </div>
    </div>
  );
}
