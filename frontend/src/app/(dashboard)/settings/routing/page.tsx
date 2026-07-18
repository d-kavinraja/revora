'use client';

import { useEffect, useState } from 'react';
import { api, ModelRoute } from '@/lib/api';
import { GitBranchIcon } from '@animateicons/react/lucide';
import { LoaderIcon } from '@/components/ui/loader-icon';
import { useToast } from '@/components/ui/toaster';

const FEATURES = ['code_review', 'security_scan', 'documentation', 'testing', 'summarization'];

interface ModelInfo {
  model: string;
  litellm_model: string;
}

export default function RoutingPage() {
  const [modelsPerProvider, setModelsPerProvider] = useState<Record<string, ModelInfo[]>>({});
  const [preferences, setPreferences] = useState<Record<string, { provider: string; model: string }>>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const { toast } = useToast();

  useEffect(() => {
    async function loadData() {
      try {
        const [modelsData, prefsData] = await Promise.all([
          api.getModelsPerProvider(),
          api.getRoutingPreferences()
        ]);
        setModelsPerProvider(modelsData);
        setPreferences(prefsData.routing || {});
      } catch (err) {
        console.error('Failed to load data', err);
        toast({ title: 'Failed to load configuration', type: 'error' });
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [toast]);

  const handleSavePreferences = async () => {
    setSaving(true);
    try {
      // Filter out empty preferences - only save ones with actual provider selected
      const validPreferences: Record<string, { provider: string; model: string }> = {};
      for (const [feature, pref] of Object.entries(preferences)) {
        if (pref.provider && pref.provider.trim() !== '') {
          validPreferences[feature] = {
            provider: pref.provider,
            model: pref.model || '',  // Empty model means use default
          };
        }
      }

      console.log('Saving preferences:', validPreferences);
      await api.updateRoutingPreferences(validPreferences);
      toast({ title: 'Routing preferences saved', type: 'success' });
    } catch (err: any) {
      console.error('Failed to save preferences', err);
      const errMsg = err.response?.data?.detail || 'Failed to save preferences';
      toast({ title: errMsg, type: 'error' });
    } finally {
      setSaving(false);
    }
  };

  const getFeatureLabel = (f: string) => {
    const labels: Record<string, string> = {
      code_review: 'PR Review',
      security_scan: 'Security Scan',
      documentation: 'Documentation',
      testing: 'Testing',
      summarization: 'Summarization',
    };
    return labels[f] || f;
  };

  const getProviderDisplayName = (p: string) => {
    const names: Record<string, string> = {
      openai: 'OpenAI',
      anthropic: 'Claude',
      gemini: 'Gemini',
      groq: 'Groq',
      deepseek: 'DeepSeek',
      openrouter: 'OpenRouter',
      azure_openai: 'Azure OpenAI',
      ollama: 'Ollama',
      cohere: 'Cohere',
      mistral: 'Mistral',
    };
    return names[p] || p;
  };

  // Get available providers (ones user has keys for)
  const availableProviders = Object.keys(modelsPerProvider);

  if (loading) {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8 flex flex-col items-center justify-center min-h-[50vh]">
        <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
        <span className="text-sm text-muted-foreground">Loading routing config...</span>
      </div>
    );
  }

  if (availableProviders.length === 0) {
    return (
      <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
        <div className="mb-8">
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <GitBranchIcon size={28} className="text-brand" />
            Model Routing
          </h1>
          <p className="mt-1 text-muted-foreground text-sm">
            Configure which provider and model to use for each feature.
          </p>
        </div>
        <div className="rounded-xl border border-border bg-surface-1 p-8 text-center">
          <GitBranchIcon size={32} className="text-muted-foreground/40 mx-auto mb-3" />
          <h3 className="font-bold text-foreground">No API keys configured</h3>
          <p className="mt-1 text-sm text-muted-foreground">
            Add an API key in Settings &gt; API Keys to configure routing.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="w-full max-w-[1200px] mx-auto p-4 md:p-6 lg:p-8">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <GitBranchIcon size={28} className="text-brand" />
            Model Routing
          </h1>
          <p className="mt-1 text-muted-foreground text-sm">
            Configure which provider and model to use for each feature.
          </p>
        </div>
        <button
          onClick={handleSavePreferences}
          disabled={saving}
          className="px-4 py-2 bg-brand text-brand-foreground hover:bg-brand-hover disabled:opacity-50 rounded-xl text-sm font-medium transition-colors shadow-lg shadow-brand/10"
        >
          {saving ? 'Saving...' : 'Save Preferences'}
        </button>
      </div>

      <div className="space-y-4">
        {FEATURES.map((feature) => {
          const selectedProvider = preferences[feature]?.provider || '';
          const modelsForProvider = selectedProvider ? (modelsPerProvider[selectedProvider] || []) : [];

          return (
            <div key={feature} className="rounded-xl border border-border bg-surface-1 p-5 backdrop-blur-md">
              <h2 className="font-bold text-foreground mb-3">{getFeatureLabel(feature)}</h2>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Provider</label>
                  <select
                    value={selectedProvider}
                    onChange={(e) =>
                      setPreferences((prev) => ({
                        ...prev,
                        [feature]: { provider: e.target.value, model: '' },
                      }))
                    }
                    className="w-full px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 transition-colors"
                  >
                    <option value="">Default (auto-select)</option>
                    {availableProviders.map((p) => (
                      <option key={p} value={p}>{getProviderDisplayName(p)}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Model</label>
                  <select
                    value={preferences[feature]?.model || ''}
                    onChange={(e) =>
                      setPreferences((prev) => ({
                        ...prev,
                        [feature]: { ...prev[feature], model: e.target.value },
                      }))
                    }
                    disabled={!selectedProvider}
                    className="w-full px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <option value="">{selectedProvider ? 'Default model' : 'Select provider first'}</option>
                    {modelsForProvider.map((m) => (
                      <option key={m.model} value={m.model}>{m.model}</option>
                    ))}
                  </select>
                </div>
              </div>
              {selectedProvider && modelsForProvider.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {modelsForProvider.slice(0, 8).map((m) => (
                    <span key={m.model} className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-surface-3 text-muted-foreground border border-border">
                      {m.model}
                    </span>
                  ))}
                  {modelsForProvider.length > 8 && (
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-brand/10 text-brand border border-brand/20">
                      +{modelsForProvider.length - 8} more
                    </span>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="mt-8 rounded-xl border border-border bg-surface-1 p-5">
        <h2 className="font-bold text-foreground mb-3">Available Providers</h2>
        <div className="flex flex-wrap gap-2">
          {availableProviders.map((p) => (
            <div key={p} className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-2 border border-border">
              <span className="font-medium text-foreground text-sm">{getProviderDisplayName(p)}</span>
              <span className="text-xs text-muted-foreground">({modelsPerProvider[p].length} models)</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
