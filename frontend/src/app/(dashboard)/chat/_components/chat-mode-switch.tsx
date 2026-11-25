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
        className={`rounded-md px-2.5 py-1.5 text-[11px] font-medium transition disabled:cursor-not-allowed disabled:opacity-45 ${activeMode === 'temporary' ? 'bg-brand text-white shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
      >
        Temporary
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={activeMode === 'persistent'}
        onClick={() => onSelect('persistent')}
        title={persistentEnabled ? 'Saved to your account' : 'Persistent Chat is read-only'}
        className={`rounded-md px-2.5 py-1.5 text-[11px] font-medium transition ${activeMode === 'persistent' ? 'bg-brand text-white shadow-sm' : 'text-muted-foreground hover:text-foreground'}`}
      >
        Persistent
        {!persistentEnabled ? <span className="ml-1 opacity-70">· read only</span> : null}
      </button>
    </div>
  );
}
