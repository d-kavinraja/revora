import Link from 'next/link';
import { ZapIcon, SettingsIcon, PlusIcon, GlobeIcon, MoreVerticalIcon } from 'lucide-react';
import { ProviderIcon } from '@/components/ui/provider-icon';
import type { Provider } from '@/lib/api';

interface ConnectedProvidersProps {
  providers: Provider[];
  loading: boolean;
}

/**
 * Connected AI Providers section — reference-image styling with the icon
 * chain (Zap) and outlined Manage Providers button.
 *
 * Shows only providers the user actually has API keys configured for
 * (the active-slug logic lives in the parent page and is preserved).
 * Status reflects real backend state — nothing is hardcoded.
 */
export function ConnectedProviders({ providers, loading }: ConnectedProvidersProps) {
  return (
    <section
      aria-label="Connected AI providers"
      className="rounded-2xl border border-border bg-surface-1 shadow-sm p-5 md:p-6"
    >
      {/* Section header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 mb-5">
        <div className="flex items-start gap-3 min-w-0">
          <span className="shrink-0 mt-0.5 flex items-center justify-center w-9 h-9 rounded-lg bg-brand/10 border border-brand/20 text-brand">
            <ZapIcon size={17} aria-hidden="true" />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-bold uppercase tracking-wider text-foreground">
              Connected AI Providers
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">
              Manage your AI provider integrations for code review.
            </p>
          </div>
        </div>
        <Link
          href="/settings/providers"
          className="inline-flex items-center justify-center gap-2 px-4 py-2 rounded-lg text-sm font-semibold text-brand border border-brand/30 bg-brand/5 hover:bg-brand/10 transition-colors shrink-0 focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
        >
          <SettingsIcon size={15} aria-hidden="true" />
          Manage Providers
        </Link>
      </div>

      {loading ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4" aria-hidden="true">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-[72px] rounded-xl border border-border bg-surface-2 animate-pulse" />
          ))}
        </div>
      ) : providers.length > 0 ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {providers.map((provider) => (
            <div
              key={provider.slug}
              className="group flex items-center gap-3.5 p-3.5 rounded-xl border border-border bg-surface-1 hover:border-brand/40 hover:shadow-sm transition-all min-w-0"
            >
              {/* Tinted provider icon square */}
              <span className="shrink-0 flex items-center justify-center w-11 h-11 rounded-xl bg-surface-2 border border-border shadow-sm">
                <ProviderIcon slug={provider.slug} size={22} />
              </span>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-bold text-foreground truncate max-w-full">
                    {provider.display_name || provider.name}
                  </span>
                  <span className="shrink-0 text-[10px] font-bold uppercase tracking-wide text-success bg-success/10 border border-success/25 px-2 py-0.5 rounded-full">
                    Active
                  </span>
                </div>
                <div className="text-xs text-muted-foreground mt-0.5 truncate font-mono">
                  {provider.default_model}
                </div>
              </div>

              {/* Kebab menu — routes to the provider's management page (real action) */}
              <Link
                href="/settings/providers"
                aria-label={`Manage ${provider.display_name || provider.name} provider`}
                title={`Manage ${provider.display_name || provider.name}`}
                className="shrink-0 p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-surface-2 transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
              >
                <MoreVerticalIcon size={16} aria-hidden="true" />
              </Link>
            </div>
          ))}

          {/* Add New Provider — routes to the existing add-key workflow */}
          <Link
            href="/settings/api-keys"
            className="sm:col-span-2 flex items-center justify-center gap-2.5 p-4 rounded-xl border border-dashed border-brand/40 bg-brand/5 hover:bg-brand/10 text-brand transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <span className="flex items-center justify-center w-7 h-7 rounded-full bg-brand/10 border border-brand/25">
              <PlusIcon size={15} aria-hidden="true" />
            </span>
            <span className="text-sm font-bold">Add New Provider</span>
            <span className="hidden sm:inline text-sm text-brand/70">— Connect more AI providers</span>
          </Link>
        </div>
      ) : (
        <div className="text-center py-10 px-4 rounded-xl border border-dashed border-border bg-surface-2">
          <GlobeIcon size={28} aria-hidden="true" className="mx-auto text-muted-foreground/60 mb-3" />
          <p className="text-sm font-semibold text-foreground">No AI providers connected yet</p>
          <p className="text-sm text-muted-foreground mt-1 mb-4">
            Configure a provider to start AI-powered reviews.
          </p>
          <Link
            href="/settings/api-keys"
            className="inline-flex items-center gap-2 text-sm font-semibold text-brand hover:text-brand-hover bg-brand/10 px-4 py-2 rounded-lg transition-colors focus-visible:ring-2 focus-visible:ring-ring/50 focus-visible:outline-none"
          >
            <PlusIcon size={14} aria-hidden="true" />
            Add your first provider
          </Link>
        </div>
      )}
    </section>
  );
}
