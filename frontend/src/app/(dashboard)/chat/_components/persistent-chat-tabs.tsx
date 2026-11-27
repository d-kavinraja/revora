'use client';

import { useEffect, useRef, useState } from 'react';
import { PlusIcon, Trash2Icon } from 'lucide-react';

import { cn } from '@/lib/utils';

interface PersistentChatTabItem {
  id: string;
  title: string;
}

interface PersistentChatTabsProps {
  items: PersistentChatTabItem[];
  activeId: string | null;
  canCreate: boolean;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onNew: () => void;
}

/** Mobile session strip. Long-press (or Delete key) arms a conversation for deletion. */
export function PersistentChatTabs({
  items,
  activeId,
  canCreate,
  onSelect,
  onDelete,
  onNew,
}: PersistentChatTabsProps) {
  const [armedId, setArmedId] = useState<string | null>(null);
  const [pressedId, setPressedId] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const clearTimer = () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  };
  useEffect(() => clearTimer, []);

  const startPress = (id: string) => {
    clearTimer();
    setPressedId(id);
    timerRef.current = window.setTimeout(() => {
      setArmedId(id);
      setPressedId(null);
      timerRef.current = null;
      navigator.vibrate?.(12);
    }, 550);
  };
  const endPress = () => {
    clearTimer();
    setPressedId(null);
  };

  return (
    <div className="flex w-full min-w-0 items-center gap-1.5">
      <div
        className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto [scrollbar-width:thin]"
        role="tablist"
        aria-label="Saved conversations"
      >
        {items.map((item, index) => {
          const active = item.id === activeId;
          const armed = item.id === armedId;
          const title = item.title.trim() || `Conversation ${index + 1}`;
          return (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={active}
              aria-label={armed ? `${title}. Tap again to delete.` : `${title}. Hold to delete, or press Delete.`}
              title={armed ? 'Tap again to delete' : title}
              onPointerDown={() => startPress(item.id)}
              onPointerUp={endPress}
              onPointerLeave={endPress}
              onPointerCancel={endPress}
              onClick={() => {
                if (armed) {
                  setArmedId(null);
                  onDelete(item.id);
                  return;
                }
                onSelect(item.id);
              }}
              onContextMenu={(event) => {
                event.preventDefault();
                onDelete(item.id);
              }}
              onKeyDown={(event) => {
                if (event.key === 'Delete' || event.key === 'Backspace') {
                  event.preventDefault();
                  onDelete(item.id);
                }
              }}
              className={cn(
                'flex h-10 min-w-0 shrink-0 items-center gap-1.5 rounded-lg border px-3 text-[13px] font-medium transition',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/50',
                active ? 'border-border/70 bg-muted/70 text-foreground' : 'border-transparent text-muted-foreground hover:bg-muted/40',
                armed && 'border-error/50 bg-error/10 text-error',
                pressedId === item.id && 'scale-[0.98] opacity-80',
              )}
            >
              <span className="block max-w-[140px] truncate">{title}</span>
              {armed || active ? (
                <Trash2Icon
                  size={13}
                  aria-hidden="true"
                  className={cn('shrink-0', !armed && 'opacity-0 group-focus-within:opacity-100')}
                />
              ) : null}
            </button>
          );
        })}
      </div>
      <button
        type="button"
        onClick={onNew}
        disabled={!canCreate}
        aria-label="New chat"
        title="New chat"
        className="chat-ink inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-border/60 transition hover:bg-muted/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
      >
        <PlusIcon size={16} />
      </button>
    </div>
  );
}
