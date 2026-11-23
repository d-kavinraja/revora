"use client";

import { useEffect, useRef } from "react";
import { PlusIcon, SquareIcon, XIcon } from "lucide-react";

import type { TemporaryChat } from "@/lib/chat-state";

interface ChatTabsProps {
  chats: TemporaryChat[];
  activeId: string | null;
  canCreate: boolean;
  isGenerating: boolean;
  /** SSR-stable base (from React.useId) used to build tab/panel DOM ids. */
  panelIdBase: string;
  onSelect: (id: string) => void;
  onNew: () => void;
  onDelete: (id: string) => void;
  onStop?: () => void;
}

export function ChatTabs({
  chats,
  activeId,
  canCreate,
  isGenerating,
  panelIdBase,
  onSelect,
  onNew,
  onDelete,
  onStop,
}: ChatTabsProps) {
  const activeRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    activeRef.current?.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
  }, [activeId]);

  return (
    <div className="w-full shrink-0 border-b border-border/60 bg-background/85 backdrop-blur-md">
      <div className="flex w-full items-center gap-1.5 py-1.5 px-4 md:px-6">
        <div
          className="flex min-w-0 flex-1 items-center gap-0.5 overflow-x-auto [scrollbar-width:thin]"
          role="tablist"
          aria-label="Chat sessions"
        >
          {chats.map((chat, index) => {
            const active = chat.id === activeId;
            const title = chat.title?.trim() || `Chat ${index + 1}`;
            const generating = active && isGenerating;
            return (
              <div
                key={chat.id}
                role="presentation"
                className={`group relative flex shrink-0 items-center rounded-md transition-colors ${
                  active ? "bg-muted/70 text-foreground" : "chat-ink hover:bg-muted/40 hover:text-foreground"
                }`}
              >
                <button
                  ref={active ? activeRef : null}
                  type="button"
                  role="tab"
                  data-active-tab={active ? "" : undefined}
                  aria-selected={active}
                  aria-controls={`${panelIdBase}-panel-${index}`}
                  onClick={() => onSelect(chat.id)}
                  className="flex max-w-[170px] items-center gap-2 px-3 py-2 pr-8 text-left text-[13px] md:max-w-[220px]"
                  title={title}
                >
                  {generating ? (
                    <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-brand animate-pulse" aria-hidden />
                  ) : null}
                  <span className="block truncate font-medium">{title}</span>
                </button>

                {generating && onStop ? (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onStop();
                    }}
                    className="chat-ink absolute right-1 inline-flex h-6 w-6 items-center justify-center rounded-md transition hover:bg-error/10 hover:text-error"
                    aria-label={`Stop generation in ${title}`}
                    title="Stop generation"
                  >
                    <SquareIcon size={11} className="fill-current" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      onDelete(chat.id);
                    }}
                    className={`chat-ink absolute right-1 inline-flex h-6 w-6 items-center justify-center rounded-md transition hover:bg-error/10 hover:text-error focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand/40 ${
                      active ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100"
                    }`}
                    aria-label={`Close ${title}`}
                    title={`Close ${title}`}
                  >
                    <XIcon size={13} />
                  </button>
                )}
              </div>
            );
          })}
        </div>

        <button
          type="button"
          onClick={onNew}
          disabled={!canCreate}
          className="chat-ink ml-auto inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md transition hover:bg-muted/50 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-45"
          aria-label="New chat"
          title={canCreate ? "New chat" : "Maximum temporary chats reached"}
        >
          <PlusIcon size={16} />
        </button>
      </div>
    </div>
  );
}
