'use client';

import { useEffect, useState, useRef } from 'react';
import { api, Provider } from '@/lib/api';
import {
  GlobeIcon,
  CircleCheckIcon,
  TriangleAlertIcon,
} from '@animateicons/react/lucide';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { useToast } from '@/components/ui/toaster';
import {
  Gemini,
  OpenAI,
  Claude,
  DeepSeek,
  Groq,
  OpenRouter,
  Azure,
  Ollama,
  Cohere,
  Mistral
} from '@lobehub/icons';

const getProviderIcon = (slug: string) => {
  switch (slug) {
    case 'gemini': return <Gemini.Color size={24} />;
    case 'openai': return <OpenAI size={24} />;
    case 'anthropic': return <Claude.Color size={24} />;
    case 'deepseek': return <DeepSeek.Color size={24} />;
    case 'groq': return <Groq size={24} />;
    case 'openrouter': return <OpenRouter size={24} />;
    case 'azure': return <Azure.Color size={24} />;
    case 'ollama': return <Ollama size={24} />;
    case 'cohere': return <Cohere.Color size={24} />;
    case 'mistral': return <Mistral.Color size={24} />;
    default: return <GlobeIcon size={24} className="text-muted-foreground" />;
  }
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

  const handleToggle = async (slug: string, enabled: boolean) => {
    try {
      const updated = await api.toggleProvider(slug, enabled);
      setProviders((prev) => prev.map((p) => (p.slug === slug ? updated : p)));
      toast({ title: `Provider ${enabled ? 'enabled' : 'disabled'}`, type: 'success' });
    } catch (err) {
      console.error('Failed to toggle provider', err);
      toast({ title: 'Failed to toggle provider', type: 'error' });
    }
  };

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
            Manage LLM providers and their capabilities. Toggle providers on/off.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {providers.map((provider) => {
          const caps = capabilities[provider.slug] || [];
          return (
            <div
              key={provider.slug}
              className="cursor-target rounded-xl border border-border bg-surface-1 p-5 backdrop-blur-md relative overflow-hidden transition-all hover:border-white/[0.08]"
            >
              <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-brand to-purple-500 opacity-50" />

              <div className="flex items-start justify-between gap-4">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2.5">
                    <span className="shrink-0 flex items-center justify-center w-8 h-8 rounded-lg bg-surface-2 border border-border">
                      {getProviderIcon(provider.slug)}
                    </span>
                    <span className="font-bold text-foreground text-base">{provider.display_name}</span>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-white/[0.04] text-muted-foreground border border-border">
                      {provider.litellm_provider}
                    </span>
                    {provider.is_enabled ? (
                      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-success/5 border-success/20 text-success">
                        <CircleCheckIcon size={12} />
                        Enabled
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full bg-error/5 border-error/20 text-error">
                        <TriangleAlertIcon size={12} />
                        Disabled
                      </span>
                    )}
                  </div>

                  <div className="mt-2 text-xs text-muted-foreground">
                    <span className="font-mono">Default: {provider.default_model}</span>
                    <span className="mx-1.5">·</span>
                    <span>Timeout: {provider.timeout_seconds}s</span>
                    <span className="mx-1.5">·</span>
                    <span>Retries: {provider.max_retries}</span>
                  </div>

                  <div className="flex flex-wrap gap-1.5 mt-3">
                    {caps.map((cap) => (
                      <span
                        key={cap}
                        className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-brand/10 text-brand border border-brand/20"
                      >
                        {getCapabilityLabel(cap)}
                      </span>
                    ))}
                  </div>
                </div>

                <div className="shrink-0">
                  <button
                    onClick={() => handleToggle(provider.slug, !provider.is_enabled)}
                    className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
                      provider.is_enabled ? 'bg-brand' : 'bg-surface-3'
                    }`}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white transition-transform ${
                        provider.is_enabled ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
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
