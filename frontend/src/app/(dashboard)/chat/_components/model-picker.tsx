"use client";

import { useMemo } from "react";
import { Check, ChevronDown, Cpu, Loader2, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Select } from "@base-ui/react/select";
import { ProviderIcon } from "@/components/ui/provider-icon";

import type { KllmStatus } from "@/lib/api";
import { type KllmModelLike, groupModels, isModelSelectable } from "@/lib/chat-state";

interface ModelPickerProps {
  status: KllmStatus | undefined;
  value: string | null;
  disabled?: boolean;
  compact?: boolean;
  onChange: (model: string) => void;
  openMenu?: 'context' | 'model' | 'effort' | null;
  onOpenMenuChange?: (menu: 'context' | 'model' | 'effort' | null) => void;
}

function statusLabel(model: KllmModelLike | null | undefined): string {
  if (!model) return "No model";
  if (isModelSelectable(model)) return "Ready";
  if (model.readiness === "loading" || model.status === "loading") return "Loading";
  if (model.readiness === "failed" || model.status === "failed") return "Failed";
  if (model.readiness === "unloaded" || model.status === "unloaded") return "Not loaded";
  return "Unavailable";
}

function ModelTrigger({
  selected,
  ready,
  canInteract,
  compact,
}: {
  selected: KllmModelLike | null;
  ready: boolean;
  canInteract: boolean;
  compact?: boolean;
}) {
  const contextPill = selected?.context_window
    ? ` · ${Math.round(selected.context_window / 1024)}K`
    : "";
  return (
    <Select.Trigger
      disabled={!canInteract}
      className={cn(
        "chat-ink group/model-trigger h-9 min-w-0 max-w-full inline-flex items-center justify-between rounded-full border bg-background/70 pl-8 pr-8 text-xs font-medium outline-none transition",
        compact
          ? "max-w-[150px] sm:max-w-[220px] md:max-w-[280px]"
          : "w-full rounded-lg px-3 py-2 text-sm",
        ready
          ? "border-border/80 hover:bg-muted/50"
          : "border-border/70",
        "focus:border-brand/50",
        "disabled:cursor-not-allowed disabled:opacity-60",
        "data-[popup-open]:bg-muted/50"
      )}
      aria-label="Select kLLM model"
      title={selected ? `${selected.key} · ${statusLabel(selected)}` : "Select model"}
    >
      <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-2.5" aria-hidden>
        {selected && !ready && (selected.readiness === "loading" || selected.status === "loading") ? (
          <Loader2 size={14} className="animate-spin" />
        ) : (
          <Cpu size={14} />
        )}
      </div>
      <Select.Value placeholder="Select model" className="truncate">
        {selected ? `${selected.key}${contextPill}` : "Select model"}
      </Select.Value>
      <Select.Icon>
        <ChevronDown
          size={14}
          className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 transition group-data-[popup-open]/model-trigger:rotate-180"
          aria-hidden
        />
      </Select.Icon>
    </Select.Trigger>
  );
}

function ModelItem({
  model,
  disabled,
}: {
  model: KllmModelLike;
  disabled: boolean;
}) {
  const contextPill = model.context_window
    ? ` ${Math.round(model.context_window / 1024)}K`
    : "";
  const status = statusLabel(model);
  const isReady = isModelSelectable(model);

  return (
    <Select.Item
      value={model.key}
      disabled={disabled}
      className={cn(
        "grid grid-cols-[18px_1fr_auto_18px] items-center gap-2 rounded-lg px-2.5 py-2 text-xs outline-none",
        "data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground",
        "data-[selected]:bg-brand/10 data-[selected]:text-brand data-[selected]:font-medium",
        disabled && "opacity-50 cursor-not-allowed"
      )}
    >
      <span className="col-start-1 flex items-center justify-center" aria-hidden>
        <ProviderIcon slug="kllm" size={14} className="shrink-0" />
      </span>
      <div className="col-start-2 flex min-w-0 items-center gap-2">
        <span className="truncate font-medium">{model.key}</span>
        {contextPill && (
          <span className="shrink-0 rounded bg-surface-2/70 px-1.5 py-0.5 text-[10px] text-muted-foreground whitespace-nowrap">
            {contextPill}
          </span>
        )}
      </div>
      {!isReady && status !== "Ready" && (
        <span className="col-start-3 shrink-0 rounded bg-surface-2/70 px-1.5 py-0.5 text-[10px] text-muted-foreground whitespace-nowrap">
          {status}
        </span>
      )}
      {isReady && (
        <span className="col-start-3 flex w-5 items-center justify-center" aria-hidden>
          <Circle size={8} className="text-emerald-500" />
        </span>
      )}
      <Select.ItemIndicator className="col-start-4 flex items-center justify-center text-brand">
        <Check size={13} />
      </Select.ItemIndicator>
    </Select.Item>
  );
}

export function ModelPicker({
  status,
  value,
  disabled,
  compact,
  onChange,
  openMenu,
  onOpenMenuChange,
}: ModelPickerProps) {
  const isModelOpen = openMenu === 'model';
  const handleModelOpenChange = (open: boolean) => {
    onOpenMenuChange?.(open ? 'model' : null);
  };

  const groups = useMemo(() => groupModels(status?.models), [status?.models]);
  const models = status?.models ?? [];
  const selected = models.find((m) => m.key === value) ?? null;
  const ready = isModelSelectable(selected);
  const canInteract = !disabled && !!status?.enabled && !!status?.reachable;

  const items = models.map((m) => ({ value: m.key, label: m.key }));

  const renderGroup = (
    label: string,
    list: KllmModelLike[],
    itemDisabled: boolean,
  ) => (
    <Select.Group className="block pb-0.5 last:pb-0">
      <Select.GroupLabel className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </Select.GroupLabel>
      {list.map((model) => (
        <ModelItem
          key={model.key}
          model={model}
          disabled={itemDisabled}
        />
      ))}
    </Select.Group>
  );

  return (
    <div className={compact ? "relative inline-flex min-w-0 items-center" : "block"}>
      <Select.Root
        value={value ?? ""}
        onValueChange={(v) => { if (v !== null) onChange(v); }}
        items={items}
        disabled={!canInteract}
        open={isModelOpen}
        onOpenChange={handleModelOpenChange}
      >
        <ModelTrigger
          selected={selected}
          ready={ready}
          canInteract={canInteract}
          compact={compact}
        />
        <Select.Portal>
          <Select.Positioner
            side="top"
            sideOffset={8}
            alignItemWithTrigger={false}
            className="z-40"
          >
            <Select.Popup
              className={cn(
                "rounded-xl border border-border bg-popover/95 p-1.5 text-popover-foreground shadow-xl backdrop-blur-md",
                compact
                  ? "w-[300px] sm:w-[340px] max-w-[calc(100vw-2rem)]"
                  : "w-full"
              )}
            >
              <Select.List className="max-h-60 space-y-0.5 overflow-y-auto scroll-py-1">
                {groups.ready.length > 0 && renderGroup("Ready", groups.ready, false)}
                {groups.loading.length > 0 && (
                  <>
                    <Select.Separator className="my-1.5 border-t border-border/60" />
                    {renderGroup("Loading", groups.loading, true)}
                  </>
                )}
                {groups.unloaded.length > 0 && (
                  <>
                    <Select.Separator className="my-1.5 border-t border-border/60" />
                    {renderGroup("Not loaded", groups.unloaded, true)}
                  </>
                )}
                {groups.failed.length > 0 && (
                  <>
                    <Select.Separator className="my-1.5 border-t border-border/60" />
                    {renderGroup("Failed", groups.failed, true)}
                  </>
                )}
                {groups.unavailable.length > 0 && (
                  <>
                    <Select.Separator className="my-1.5 border-t border-border/60" />
                    {renderGroup("Unavailable", groups.unavailable, true)}
                  </>
                )}
                {models.length === 0 && (
                  <div className="px-2.5 py-3 text-center text-xs text-muted-foreground">
                    No models available
                  </div>
                )}
              </Select.List>
            </Select.Popup>
          </Select.Positioner>
        </Select.Portal>
      </Select.Root>
    </div>
  );
}