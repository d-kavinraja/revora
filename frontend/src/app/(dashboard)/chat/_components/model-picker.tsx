"use client";

import { Fragment, useMemo } from "react";
import { Check, ChevronDown, Cpu, Loader2, Circle } from "lucide-react";
import { cn } from "@/lib/utils";
import { Select } from "@base-ui/react/select";

import type { ChatCatalog, ChatCatalogProvider } from "@/lib/api";
import {
  type GroupedModels,
  type KllmModelLike,
  formatContextWindow,
  groupCatalogModels,
  isModelSelectable,
  modelDisplayName,
  providerLabel,
  readinessReason,
  resolveSelectedModel,
  HOSTED_PROVIDER,
  KLLM_PROVIDER,
  HOSTED_PROVIDER_LABEL,
  KLLM_PROVIDER_LABEL,
} from "@/lib/chat-state";

import { ModelIcon } from "@/components/ui/model-icon";

interface ModelPickerProps {
  catalog: ChatCatalog | undefined;
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
  if (model.readiness === "verifying" || model.status === "verifying") return "Verifying";
  if (model.readiness === "loading" || model.status === "loading") return "Loading";
  if (model.readiness === "failed" || model.status === "failed") return "Failed";
  if (model.readiness === "unloaded" || model.status === "unloaded") return "Not loaded";
  return "Unavailable";
}

/** A selected key that is no longer in the catalog is still shown, but never selectable. */

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
  const contextLabel = formatContextWindow(selected?.context_window);
  const contextPill = contextLabel ? ` · ${contextLabel}` : "";
  const loading =
    !!selected &&
    (selected.readiness === "loading" ||
      selected.status === "loading" ||
      selected.readiness === "verifying" ||
      selected.status === "verifying");
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
      aria-label="Select chat model"
      title={selected ? `${modelDisplayName(selected)} · ${statusLabel(selected)}` : "Select model"}
    >
      <div className="pointer-events-none absolute inset-y-0 left-0 flex items-center pl-2.5" aria-hidden>
        {loading ? (
          <Loader2 size={14} className="animate-spin" />
        ) : selected ? (
          <ModelIcon model={selected} size={14} className="shrink-0" />
        ) : (
          <Cpu size={14} />
        )}
      </div>
      <Select.Value placeholder="Select model" className="truncate">
        {selected ? `${modelDisplayName(selected)}${contextPill}` : "Select model"}
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
  const contextLabel = formatContextWindow(model.context_window);
  const status = statusLabel(model);
  const isReady = isModelSelectable(model);
  const reason = readinessReason(model);

  return (
    <Select.Item
      value={model.key}
      disabled={disabled}
      title={reason ?? `${modelDisplayName(model)} · ${status}`}
      className={cn(
        "grid grid-cols-[18px_1fr_auto_18px] items-center gap-2 rounded-lg px-2.5 py-2 text-xs outline-none",
        "data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground",
        "data-[selected]:bg-brand/10 data-[selected]:text-brand data-[selected]:font-medium",
        disabled && "opacity-50 cursor-not-allowed"
      )}
    >
      <span className="col-start-1 flex items-center justify-center" aria-hidden>
        <ModelIcon model={model} size={14} className="shrink-0" />
      </span>
      <div className="col-start-2 flex min-w-0 items-center gap-2">
        <span className="truncate font-medium">{modelDisplayName(model)}</span>
        {contextLabel && (
          <span className="shrink-0 rounded bg-surface-2/70 px-1.5 py-0.5 text-[10px] text-muted-foreground whitespace-nowrap">
            {contextLabel}
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

/** Backend-confirmed provider state, shown above that provider's own section. */
function providerNotice(provider: ChatCatalogProvider | undefined): string | null {
  if (!provider) return null;
  if (!provider.enabled) return "Disabled";
  if (provider.waking) return "Waking the hosted machine";
  if (!provider.configured) return "Not configured";
  if (!provider.reachable) return "Unreachable";
  if (provider.stale) return "Status stale";
  if (provider.discovery_ok === false) return "Verifying";
  return null;
}

interface ProviderSection {
  provider: 'hosted-ollama' | 'kllm';
  label: string;
  groups: GroupedModels;
  notice: string | null;
}

export function ModelPicker({
  catalog,
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

  const groups = useMemo(() => groupCatalogModels(catalog?.models), [catalog?.models]);
  const models = catalog?.models ?? [];
  const selected = resolveSelectedModel(models, value);
  const ready = isModelSelectable(selected);
  const providers = catalog?.providers ?? [];
  const providerFor = (id: string) => providers.find((p) => p.provider === id);

  // Selection is gated per item and per provider: a ready kLLM model stays
  // selectable even when the hosted provider is stale, and vice versa.
  const canInteract =
    !disabled &&
    !!catalog?.enabled &&
    (providerFor(HOSTED_PROVIDER)?.enabled === true ||
      providerFor(KLLM_PROVIDER)?.enabled === true);

  const items = models.map((m) => ({ value: m.key, label: modelDisplayName(m) }));

  const sections: ProviderSection[] = [
    {
      provider: HOSTED_PROVIDER,
      label: HOSTED_PROVIDER_LABEL,
      groups: groups.hosted,
      notice: providerNotice(providerFor(HOSTED_PROVIDER)),
    },
    {
      provider: KLLM_PROVIDER,
      label: KLLM_PROVIDER_LABEL,
      groups: groups.kllm,
      notice: providerNotice(providerFor(KLLM_PROVIDER)),
    },
  ];

  const renderGroup = (label: string, list: KllmModelLike[]) => {
    if (list.length === 0) return null;
    return (
      <Select.Group className="block pb-0.5 last:pb-0">
        <Select.GroupLabel className="px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          {label}
        </Select.GroupLabel>
        {list.map((model) => (
          <ModelItem
            key={model.key}
            model={model}
            // Only a backend-confirmed ready model is selectable. Installed but
            // unloaded models stay visible in "Not loaded" and are disabled.
            disabled={!isModelSelectable(model)}
          />
        ))}
      </Select.Group>
    );
  };

  const renderSection = (section: ProviderSection, index: number) => {
    const { ready: readyList, loading, verifying, unloaded, failed, unavailable } = section.groups;
    const empty =
      readyList.length === 0 &&
      loading.length === 0 &&
      verifying.length === 0 &&
      unloaded.length === 0 &&
      failed.length === 0 &&
      unavailable.length === 0;
    return (
      <Fragment key={section.provider}>
        {index > 0 && <Select.Separator className="my-1.5 border-t border-border/60" />}
        {/* Provider heading: status groups below it belong to this provider only. */}
        <div className="flex items-center justify-between gap-2 px-2.5 py-1.5 text-[11px] font-semibold uppercase tracking-wider text-foreground/85">
          <span className="truncate">{section.label}</span>
          {section.notice ? (
            <span className="shrink-0 rounded bg-surface-2/70 px-1.5 py-0.5 text-[10px] font-medium normal-case text-muted-foreground whitespace-nowrap">
              {section.notice}
            </span>
          ) : null}
        </div>
        {renderGroup("Ready", readyList)}
        {renderGroup("Loading", loading)}
        {renderGroup("Verifying", verifying)}
        {renderGroup("Not loaded", unloaded)}
        {renderGroup("Failed", failed)}
        {renderGroup("Unavailable", unavailable)}
        {empty && (
          <div className="px-2.5 py-2 text-[11px] text-muted-foreground">
            No {section.provider === HOSTED_PROVIDER ? "hosted" : "kLLM"} models reported.
          </div>
        )}
      </Fragment>
    );
  };

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
              <Select.List className="max-h-72 space-y-0.5 overflow-y-auto scroll-py-1">
                {models.length === 0 ? (
                  <div className="px-2.5 py-3 text-center text-xs text-muted-foreground">
                    No models available
                  </div>
                ) : (
                  sections.map(renderSection)
                )}
                {selected && !isModelSelectable(selected) ? (
                  <div className="mt-1 border-t border-border/60 px-2.5 py-1.5 text-[10px] text-muted-foreground">
                    {providerLabel(selected)} · {statusLabel(selected)}
                    {readinessReason(selected) ? ` — ${readinessReason(selected)}` : ""}
                  </div>
                ) : null}
              </Select.List>
            </Select.Popup>
          </Select.Positioner>
        </Select.Portal>
      </Select.Root>
    </div>
  );
}
