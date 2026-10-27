'use client';

import { useEffect, useState } from 'react';
import { api, Provider } from '@/lib/api';
import {
  GlobeIcon,
  CircleCheckIcon,
  TriangleAlertIcon,
} from '@animateicons/react/lucide';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { useToast } from '@/components/ui/toaster';
import { ProviderIcon } from '@/components/ui/provider-icon';
import { Pill, type PillTone } from '@/components/shared/pill';
import { formatDateTime } from '@/components/shared/time-ago';

const STATUS_META: Record<string, { label: string; tone: PillTone }> = {
  available: { label: 'Available', tone: 'success' },
  under_testing: { label: 'Under testing', tone: 'warning' },
  coming_soon: { label: 'Coming soon', tone: 'info' },
  unavailable: { label: 'Temporarily unavailable', tone: 'error' },
  disabled: { label: 'Disabled', tone: 'muted' },
};

export default function ProvidersPage() {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [loading, setLoading] = useState(true);
  const [capabilities, setCapabilities] = useState<Record<string, string[]>>({});
  const { toast } = useToast();

  useEffect(() => {
    async function loadData() {
      try {
        const [provData, capData] = await Promise.all([
          api.getProviders(),
          api.getProviderCapabilities(),
        ]);
        setProviders(provData);
        setCapabilities(capData);
      } catch (err) {
        console.error('Failed to load providers', err);
        toast({ title: 'Failed to load providers', type: 'error' });
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [toast]);

  const getCapabilityLabel = (cap: string) => {
    const labels: Record<string, string> = {
      streaming: 'Streaming',
      vision: 'Vision',
      function_calling: 'Functions',
      reasoning: 'Reasoning',
    };
    return labels[cap] || cap;
  };

  if (loading) {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 flex flex-col items-center justify-center min-h-[50vh]">
        <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
        <span className="text-sm text-muted-foreground">Loading providers...</span>
      </div>
    );
  }

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <GlobeIcon size={28} className="text-brand" />
            Provider Registry
          </h1>
          <p className="mt-1 text-muted-foreground text-sm">
            View LLM providers and their capabilities. Availability is managed by the platform team.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {providers.map((provider) => {
          const caps = capabilities[provider.slug] || [];
          const statusMeta = STATUS_META[provider.status] ?? {
            label: provider.status,
            tone: 'muted' as PillTone,
          };
          return (
            <div
              key={provider.slug}
              className="cursor-target rounded-xl border border-border bg-surface-1 p-5 relative overflow-hidden transition-all hover:border-brand/30"
            >
              <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-brand to-brand-hover opacity-50" />

              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5">
                    <span className="shrink-0 flex items-center justify-center w-8 h-8 rounded-lg bg-surface-2 border border-border">
                      <ProviderIcon slug={provider.slug} size={16} />
                    </span>
                    <span className="font-bold text-foreground text-base">{provider.display_name}</span>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-white/[0.04] text-muted-foreground border border-border">
                      {provider.litellm_provider}
                    </span>
                    <Pill tone={statusMeta.tone}>
                      {statusMeta.tone === 'success' && <CircleCheckIcon size={12} />}
                      {(statusMeta.tone === 'warning' || statusMeta.tone === 'error') && (
                        <TriangleAlertIcon size={12} />
                      )}
                      {statusMeta.label}
                    </Pill>
                  </div>

                  <div className="mt-2 text-xs text-muted-foreground">
                    <span className="font-mono">Default: {provider.default_model}</span>
                    <span className="mx-1.5">·</span>
                    <span>Timeout: {provider.timeout_seconds}s</span>
                    <span className="mx-1.5">·</span>
                    <span>Retries: {provider.max_retries}</span>
                  </div>

                  {provider.status_message && (
                    <p className="mt-2 text-xs text-foreground/80 border-l-2 border-warning/50 pl-2">
                      {provider.status_message}
                    </p>
                  )}
                  {provider.status === 'unavailable' && provider.status_expires_at && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      Expected back {formatDateTime(provider.status_expires_at)}
                    </p>
                  )}

                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {caps.map((cap) => (
                      <span
                        key={cap}
                        className="text-xs font-medium px-2 py-0.5 rounded-full bg-brand/10 text-brand border border-brand/30"
                      >
                        {getCapabilityLabel(cap)}
                      </span>
                    ))}
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <footer className="mt-12 border-t border-border pt-6 text-center text-xs text-muted-foreground">
        &copy; {new Date().getFullYear()} Revora. All rights reserved.
      </footer>
    </div>
  );
}
