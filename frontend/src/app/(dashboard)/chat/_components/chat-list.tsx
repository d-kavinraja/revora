'use client';

import { PlusIcon, TrashIcon } from '@animateicons/react/lucide';

import type { TemporaryChat } from '@/lib/chat-state';

interface ChatListProps {
  chats: TemporaryChat[];
  activeId: string | null;
  canCreate: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
}

export function ChatList({ chats, activeId, canCreate, onSelect, onNew, onDelete }: ChatListProps) {
  return (
    <aside className="flex h-full min-h-0 flex-col rounded-xl border border-border bg-surface-1">
      <div className="flex items-center justify-between gap-2 border-b border-border p-3">
        <div>
          <p className="text-sm font-semibold text-foreground">Chats</p>
          <p className="text-[11px] text-muted-foreground">Temporary, in-memory only</p>
        </div>
        <button
          type="button"
          onClick={onNew}
          disabled={!canCreate}
          className="inline-flex items-center gap-1 rounded-lg border border-brand/40 bg-brand/10 px-2.5 py-1.5 text-xs font-medium text-brand transition hover:bg-brand/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <PlusIcon size={14} />
          New
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {chats.length === 0 ? (
          <p className="px-2 py-3 text-xs text-muted-foreground">No temporary chats.</p>
        ) : (
          <ul className="space-y-1">
            {chats.map((chat) => {
              const active = chat.id === activeId;
              return (
                <li key={chat.id}>
                  <div
                    className={`group flex items-center gap-1 rounded-lg border px-2 py-2 transition ${
                      active
                        ? 'border-brand/40 bg-brand/10'
                        : 'border-transparent hover:border-border hover:bg-surface-2/60'
                    }`}
                  >
                    <button
                      type="button"
                      onClick={() => onSelect(chat.id)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <p className={`truncate text-sm ${active ? 'text-foreground' : 'text-foreground/90'}`}>
                        {chat.title || 'New chat'}
                      </p>
                      <p className="truncate text-[11px] text-muted-foreground">
                        {chat.model || 'No model selected'}
                      </p>
                    </button>
                    <button
                      type="button"
                      onClick={() => onDelete(chat.id)}
                      className="rounded-md p-1.5 text-muted-foreground opacity-70 transition hover:bg-error/10 hover:text-error group-hover:opacity-100"
                      aria-label={`Delete ${chat.title || 'chat'}`}
                      title="Delete chat"
                    >
                      <TrashIcon size={14} />
                    </button>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      <div className="border-t border-border p-3 text-[11px] leading-relaxed text-muted-foreground">
        Cleared on refresh, tab close, logout, or session loss.
      </div>
    </aside>
  );
}
