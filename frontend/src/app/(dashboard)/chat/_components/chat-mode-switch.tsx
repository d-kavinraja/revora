'use client';

interface ChatModeSwitchProps {
  activeMode: 'temporary' | 'persistent';
  temporaryEnabled: boolean;
  persistentEnabled: boolean;
  onSelect: (mode: 'temporary' | 'persistent') => void;
}

export function ChatModeSwitch({
  activeMode,
  temporaryEnabled,
  persistentEnabled,
  onSelect,
}: ChatModeSwitchProps) {
  return (
    <div
      role="tablist"
      aria-label="Chat mode"
      className="inline-flex shrink-0 items-center rounded-lg border border-border/70 bg-background/60 p-0.5"
    >
      <button
        type="button"
        role="tab"
        aria-selected={activeMode === 'temporary'}
        disabled={!temporaryEnabled}
        onClick={() => onSelect('temporary')}
        className={`min-h-8 shrink-0 rounded-md px-2 py-1 text-[10px] font-medium transition sm:px-2.5 sm:py-1.5 sm:text-[11px] disabled:cursor-not-allowed disabled:opacity-45 ${activeMode === 'temporary' ? 'bg-brand text-white shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
      >
        Temporary
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={activeMode === 'persistent'}
        onClick={() => onSelect('persistent')}
        title={persistentEnabled ? 'Saved to your account' : 'Persistent Chat is read-only'}
        className={`min-h-8 shrink-0 rounded-md px-2 py-1 text-[10px] font-medium transition sm:px-2.5 sm:py-1.5 sm:text-[11px] ${activeMode === 'persistent' ? 'bg-brand text-white shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
      >
        Persistent
        {!persistentEnabled ? <span className="ml-1 opacity-70">· read only</span> : null}
      </button>
    </div>
  );
}
