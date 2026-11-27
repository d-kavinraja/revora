"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowUpIcon,
  BrainIcon,
  ChevronDownIcon,
  CheckIcon,
  LoaderCircleIcon,
  MicIcon,
  SquareIcon,
  XIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Select } from "@base-ui/react/select";

import { HandoffBeam, type BeamPhase } from "@/components/ui/handoff-beam";
import type { ChatCatalog } from "@/lib/api";
import type { ReasoningEffort } from "@/lib/chat-api";
import { CHAT_MAX_MESSAGE_CHARS } from "@/lib/chat-state";
import { useChatKeyboard } from "@/lib/use-chat-keyboard";
import type { SpeechPhase } from "@/lib/speech";

import { ModelPicker } from "./model-picker";

export interface ComposerSpeechControls {
  enabled: boolean;
  phase: SpeechPhase;
  error: string | null;
  readiness: 'disabled' | 'ready' | 'unavailable' | 'recovering' | 'authentication_error' | 'configuration_error' | 'error';
  elapsedMs: number;
  maxSeconds: number;
  onStart: () => void;
  onStop: () => void;
  onCancel: () => void;
}

interface ChatComposerProps {
  value: string;
  disabled: boolean;
  sending: boolean;
  canStop: boolean;
  helperText?: string | null;
  modelStatus: ChatCatalog | undefined;
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
  speech?: ComposerSpeechControls;
  caretRequest?: number;
}

const SPEECH_ACTIVE: SpeechPhase[] = [
  'requesting',
  'recording',
  'uploading',
  'queued',
  'processing',
];

function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, '0')}`;
}

function speechStatus(phase: SpeechPhase, elapsedMs: number, maxSeconds: number): string | null {
  if (phase === 'requesting') return 'Waiting for microphone permission…';
  if (phase === 'recording') {
    return `Recording ${formatClock(elapsedMs)} of ${formatClock(maxSeconds * 1000)}`;
  }
  if (phase === 'uploading') return 'Sending recording…';
  if (phase === 'queued') return 'Waiting for the transcriber…';
  if (phase === 'processing') return 'Transcribing…';
  if (phase === 'done') return 'Transcript added. Review it, then send when ready.';
  return null;
}

// The visible recording timer changes four times a second. Keep it out of the
// live region so a screen reader is not interrupted on every tick; announce
// only the phase change itself.
function speechAnnouncement(phase: SpeechPhase): string {
  if (phase === 'requesting') return 'Waiting for microphone permission.';
  if (phase === 'recording') return 'Recording. Use Stop recording and transcribe when finished.';
  if (phase === 'uploading') return 'Sending recording.';
  if (phase === 'queued') return 'Waiting for the transcriber.';
  if (phase === 'processing') return 'Transcribing.';
  if (phase === 'done') return 'Transcript added. Review it, then send when ready.';
  return '';
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
        "chat-ink group/effort-trigger h-9 w-[88px] max-sm:w-[76px] max-sm:px-2 sm:w-auto shrink-0 inline-flex items-center justify-between gap-2 rounded-full border border-border/70 bg-transparent px-2.5 text-xs font-medium outline-none transition hover:bg-muted/50 hover:text-foreground focus:border-brand/50 disabled:cursor-not-allowed disabled:opacity-60",
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
  speech,
  caretRequest = 0,
}: ChatComposerProps) {
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const keyboardOpen = useChatKeyboard();
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
    const cap = keyboardOpen ? 120 : 220;
    el.style.height = `${Math.min(el.scrollHeight, cap)}px`;
  }, [value, keyboardOpen]);

  useEffect(() => {
    if (!caretRequest) return;
    const el = textareaRef.current;
    if (!el) return;
    el.focus();
    const end = el.value.length;
    el.setSelectionRange(end, end);
  }, [caretRequest]);

  const speechActive = speech ? SPEECH_ACTIVE.includes(speech.phase) : false;
  const speechRecording = speech?.phase === 'recording';
  const speechStatusText = speech
    ? speechStatus(speech.phase, speech.elapsedMs, speech.maxSeconds)
    : null;
  const voiceNotice = speech?.error
    ? { text: speech.error, alert: true }
    : speech?.enabled && speech.readiness !== 'ready'
      ? {
          alert: false,
          text: speech.readiness === 'recovering'
            ? 'Voice input is recovering. Try again shortly.'
            : speech.readiness === 'disabled'
              ? 'Voice input is turned off by an administrator.'
              : speech.readiness === 'authentication_error'
                ? 'Voice input could not authenticate.'
                : 'Voice input is temporarily unavailable. Retrying automatically.',
        }
      : null;

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
    <div className="shrink-0 px-4 pt-1.5 pb-[calc(0.5rem+env(safe-area-inset-bottom))] md:px-6 md:pt-2 md:pb-3">
      <div className="mx-auto w-full max-w-3xl">
        {voiceNotice ? (
          <>
            <div
              role={voiceNotice.alert ? 'alert' : 'status'}
              className={cn(
                'mb-1.5 flex max-w-full items-center gap-2 self-start rounded-full border border-border/60 bg-muted/40 px-2.5 py-0.5 text-[11px] text-muted-foreground',
                keyboardOpen && 'max-md:hidden',
              )}
            >
              <span aria-hidden className="h-1.5 w-1.5 shrink-0 rounded-full bg-warning" />
              <span className="truncate">{voiceNotice.text}</span>
            </div>
            {keyboardOpen ? <span className="sr-only" role="status">{voiceNotice.text}</span> : null}
          </>
        ) : helperText ? (
          <p className="chat-ink mb-2 px-2 text-xs">{helperText}</p>
        ) : null}

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

            {speechStatusText ? (
              <div
                role="status"
                aria-live="polite"
                className="mt-1 flex min-w-0 items-center gap-2 px-0.5 text-[11px] text-muted-foreground"
              >
                <span className="sr-only">{speechAnnouncement(speech?.phase ?? 'idle')}</span>
                <span
                  aria-hidden
                  className={cn(
                    "h-1.5 w-1.5 shrink-0 rounded-full",
                    speechRecording ? "bg-brand motion-safe:animate-pulse" : "bg-muted-foreground/60",
                  )}
                />
                <span aria-hidden className="truncate">{speechStatusText}</span>
              </div>
            ) : null}

            <div className="mt-1 flex items-center justify-between gap-2 pt-1">
              <div className="flex min-w-0 flex-1 items-center gap-1.5">
                <ModelPicker
                  catalog={modelStatus}
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
                        className="w-56 max-w-[calc(100vw-24px)] rounded-xl border border-border bg-popover/95 p-1.5 text-popover-foreground shadow-xl backdrop-blur-md"
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
                {speech?.enabled ? (
                  <>
                    {speechRecording ? (
                      <button
                        type="button"
                        onClick={speech.onStop}
                        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full md:h-9 md:w-9 bg-brand text-brand-foreground transition hover:bg-brand/90"
                        aria-label="Stop recording and transcribe"
                        title="Stop recording and transcribe"
                      >
                        <MicIcon size={16} />
                      </button>
                    ) : speechActive ? (
                      <button
                        type="button"
                        disabled
                        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full md:h-9 md:w-9 border border-border/70 text-muted-foreground"
                        aria-label={
                          speech.phase === 'requesting'
                            ? 'Waiting for microphone permission'
                            : 'Transcribing voice input'
                        }
                        title={
                          speech.phase === 'requesting'
                            ? 'Waiting for microphone permission'
                            : 'Transcribing voice input'
                        }
                      >
                        <LoaderCircleIcon size={16} className="animate-spin" />
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={speech.onStart}
                        disabled={disabled || sending || speech.readiness !== 'ready'}
                        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full md:h-9 md:w-9 border border-border/70 text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
                        aria-label="Start voice input"
                        title={
                          speech.readiness === 'ready'
                            ? 'Start voice input'
                            : speech.readiness === 'disabled'
                              ? 'Voice input is turned off by an administrator.'
                              : speech.readiness === 'authentication_error'
                                ? 'Voice input could not authenticate.'
                                : 'Voice input is temporarily unavailable. Retrying automatically.'
                        }
                      >
                        <MicIcon size={16} />
                      </button>
                    )}
                    {speechActive ? (
                      <button
                        type="button"
                        onClick={speech.onCancel}
                        className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full md:h-9 md:w-9 text-muted-foreground transition hover:bg-muted hover:text-foreground"
                        aria-label="Cancel voice input"
                        title="Cancel voice input"
                      >
                        <XIcon size={15} />
                      </button>
                    ) : null}
                  </>
                ) : null}
                {showCount ? (
                  <span className={`hidden text-[11px] tabular-nums md:inline ${nearLimit ? "text-warning" : "chat-ink"}`} title="Message length / safety ceiling">
                    {value.length.toLocaleString()}
                  </span>
                ) : null}
                {sending && canStop ? (
                  <button
                    type="button"
                    onClick={onStop}
                    className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full md:h-9 md:w-9 bg-foreground text-background transition hover:opacity-90"
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
                    className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-full md:h-9 md:w-9 bg-foreground text-background transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-30"
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
        <p className="chat-ink mt-1 px-2 text-center text-[10px] md:mt-2 md:text-[11px]">
          AI can make mistakes. Check important information.
        </p>
      </div>
    </div>
  );
}