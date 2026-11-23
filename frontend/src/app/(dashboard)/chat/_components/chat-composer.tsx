"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUpIcon, BrainIcon, ChevronDownIcon, CheckIcon, SquareIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Select } from "@base-ui/react/select";

import { HandoffBeam, type BeamPhase } from "@/components/ui/handoff-beam";
import type { KllmStatus } from "@/lib/api";
import type { ReasoningEffort } from "@/lib/chat-api";
import { CHAT_MAX_MESSAGE_CHARS } from "@/lib/chat-state";

import { ModelPicker } from "./model-picker";

interface ChatComposerProps {
  value: string;
  disabled: boolean;
  sending: boolean;
  canStop: boolean;
  helperText?: string | null;
  modelStatus: KllmStatus | undefined;
  modelValue: string | null;
  reasoningEffort: ReasoningEffort;
  onReasoningEffortChange: (effort: ReasoningEffort) => void;
  onModelChange: (model: string) => void;
  onChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
  generationPhase?: 'preparing' | 'thinking' | 'generating' | null;
  openMenu?: 'context' | 'model' | 'effort' | null;
  onOpenMenuChange?: (menu: 'context' | 'model' | 'effort' | null) => void;
}

const EFFORT_ITEMS: {
  value: ReasoningEffort;
  label: string;
  subtitle: string;
  icon: React.ReactNode;
}[] = [
  {
    value: "low",
    label: "Low",
    subtitle: "Fastest responses, minimal reasoning",
    icon: <BrainIcon size={13} className="text-muted-foreground" />,
  },
  {
    value: "medium",
    label: "Medium",
    subtitle: "Balanced speed and reasoning depth",
    icon: <BrainIcon size={13} className="text-muted-foreground" />,
  },
  {
    value: "high",
    label: "High",
    subtitle: "Deeper multi-step problem solving",
    icon: <BrainIcon size={13} className="text-muted-foreground" />,
  },
  {
    value: "max",
    label: "Max",
    subtitle: "Maximum reasoning budget for complex tasks",
    icon: <BrainIcon size={13} className="text-muted-foreground" />,
  },
];

function EffortTrigger({ value, disabled }: {
  value: ReasoningEffort;
  disabled: boolean;
}) {
  const current = EFFORT_ITEMS.find((i) => i.value === value) ?? EFFORT_ITEMS[1];
  return (
    <Select.Trigger
      disabled={disabled}
      className={cn(
        "chat-ink group/effort-trigger h-9 w-[100px] sm:w-auto shrink-0 inline-flex items-center justify-between gap-2 rounded-full border border-border/70 bg-transparent px-3 text-xs font-medium outline-none transition hover:bg-muted/50 hover:text-foreground focus:border-brand/50 disabled:cursor-not-allowed disabled:opacity-60",
        "data-[popup-open]:bg-muted/50"
      )}
      aria-label="Reasoning effort"
      title="Reasoning effort (sent to gateway when supported)"
    >
      <BrainIcon size={13} className="shrink-0" aria-hidden />
      <span className="truncate text-ellipsis">{current.label}</span>
      <Select.Icon>
        <ChevronDownIcon
          size={13}
          className="pointer-events-none transition group-data-[popup-open]/effort-trigger:rotate-180"
          aria-hidden
        />
      </Select.Icon>
    </Select.Trigger>
  );
}

export function ChatComposer({
  value,
  disabled,
  sending,
  canStop,
  helperText,
  modelStatus,
  modelValue,
  reasoningEffort,
  onReasoningEffortChange,
  onModelChange,
  onChange,
  onSend,
  onStop,
  generationPhase,
  openMenu,
  onOpenMenuChange,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const [focused, setFocused] = useState(false);
  const nearLimit = value.length > CHAT_MAX_MESSAGE_CHARS * 0.92;
  const showCount = value.length > 0;

  const isEffortOpen = openMenu === 'effort';
  const handleEffortOpenChange = (open: boolean) => {
    onOpenMenuChange?.(open ? 'effort' : null);
  };

  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = "0px";
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`;
  }, [value]);

  const phase: BeamPhase = sending
    ? generationPhase === "generating"
      ? "speaking"
      : generationPhase === "thinking" || generationPhase === "preparing"
        ? "thinking"
        : "speaking"
    : focused || value.trim().length > 0
      ? "listening"
      : "idle";
  const isActive = focused || value.trim().length > 0;

  return (
    <div className="shrink-0 px-3 pt-1.5 pb-[calc(0.5rem+env(safe-area-inset-bottom))] md:px-6 md:pt-2 md:pb-3">
      <div className="mx-auto w-full max-w-3xl">
        {helperText ? <p className="chat-ink mb-2 px-2 text-xs">{helperText}</p> : null}

        <HandoffBeam
          phase={phase}
          radius={28}
          reach={isActive ? 24 : 18}
          intensity={isActive ? 0.9 : 0.55}
          palette="ember"
          phaseLabels={{
            idle: "Chat idle",
            listening: "Listening for your message",
            thinking: "Thinking",
            speaking: "Generating response",
          }}
          className="composer-glow rounded-3xl border bg-card/90 backdrop-blur-md transition-all duration-200 border-slate-300/90 dark:border-white/15 shadow-md dark:shadow-lg dark:shadow-black/40 hover:border-brand/45 hover:shadow-lg focus-within:border-brand/80 dark:focus-within:border-brand/90 focus-within:ring-4 focus-within:ring-brand/15"
        >
          <div className="px-4 pt-3 pb-2 md:px-5 md:pt-4">
            <textarea
              ref={textareaRef}
              value={value}
              onChange={(e) => onChange(e.target.value.slice(0, CHAT_MAX_MESSAGE_CHARS))}
              onFocus={() => setFocused(true)}
              onBlur={() => setFocused(false)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  if (!disabled && !sending && value.trim()) onSend();
                }
              }}
              rows={1}
              placeholder="Type a message..."
              className="max-h-[min(220px,32dvh)] min-h-[52px] w-full resize-none bg-transparent px-0 py-1 text-[15px] leading-6 text-foreground outline-none placeholder:text-muted-foreground/70"
              aria-label="Chat message"
            />

            <div className="mt-1 flex items-center justify-between gap-2 pt-1">
              <div className="flex min-w-0 flex-1 items-center gap-1.5 flex-wrap">
                <ModelPicker
                  status={modelStatus}
                  value={modelValue}
                  disabled={sending}
                  compact
                  onChange={onModelChange}
                  openMenu={openMenu}
                  onOpenMenuChange={onOpenMenuChange}
                />
                <Select.Root
                  value={reasoningEffort}
                  onValueChange={(v) => onReasoningEffortChange(v as ReasoningEffort)}
                  items={EFFORT_ITEMS.map((i) => ({ value: i.value, label: i.label }))}
                  disabled={sending}
                  open={isEffortOpen}
                  onOpenChange={handleEffortOpenChange}
                >
                  <EffortTrigger
                    value={reasoningEffort}
                    disabled={sending}
                  />
                  <Select.Portal>
                    <Select.Positioner
                      side="top"
                      sideOffset={8}
                      alignItemWithTrigger={false}
                      className="z-40"
                    >
                      <Select.Popup
                        className="w-56 rounded-xl border border-border bg-popover/95 p-1.5 text-popover-foreground shadow-xl backdrop-blur-md"
                      >
                        <Select.List className="max-h-60 space-y-0.5 overflow-y-auto">
                          {EFFORT_ITEMS.map((item) => (
                            <Select.Item
                              key={item.value}
                              value={item.value}
                              className={cn(
                                "grid grid-cols-[16px_1fr_14px] items-center gap-2 rounded-lg px-2.5 py-2 text-xs outline-none",
                                "data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground",
                                "data-[selected]:bg-brand/10 data-[selected]:text-brand data-[selected]:font-medium"
                              )}
                            >
                              <span className="col-start-1 flex items-center justify-center" aria-hidden>{item.icon}</span>
                              <div className="col-start-2 min-w-0">
                                <span className="block truncate font-medium">{item.label}</span>
                                <span className="block text-[11px] text-muted-foreground truncate">{item.subtitle}</span>
                              </div>
                              <Select.ItemIndicator className="col-start-3 flex items-center justify-center text-brand">
                                <CheckIcon size={13} />
                              </Select.ItemIndicator>
                            </Select.Item>
                          ))}
                        </Select.List>
                      </Select.Popup>
                    </Select.Positioner>
                  </Select.Portal>
                </Select.Root>
              </div>

              <div className="flex items-center gap-2">
                {showCount ? (
                  <span className={`hidden text-[11px] tabular-nums md:inline ${nearLimit ? "text-warning" : "chat-ink"}`} title="Message length / safety ceiling">
                    {value.length.toLocaleString()}
                  </span>
                ) : null}
                {sending && canStop ? (
                  <button
                    type="button"
                    onClick={onStop}
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition hover:opacity-90"
                    aria-label="Stop generation"
                    title="Stop generation"
                  >
                    <SquareIcon size={13} className="fill-current" />
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={onSend}
                    disabled={disabled || sending || !value.trim()}
                    className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-foreground text-background transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
                    aria-label="Send message"
                    title="Send message"
                  >
                    <ArrowUpIcon size={16} strokeWidth={2.5} />
                  </button>
                )}
              </div>
            </div>
          </div>
        </HandoffBeam>
        <p className="chat-ink mt-1.5 px-2 text-center text-[11px] md:mt-2">
          AI can make mistakes. Check important information.
        </p>
      </div>
    </div>
  );
}