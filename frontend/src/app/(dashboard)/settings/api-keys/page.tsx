'use client';

import { useEffect, useState, useRef } from 'react';
import { api, ApiKey, ThemeConfig } from '@/lib/api';
import { 
  KeyIcon, 
  TrashIcon, 
  PlusIcon, 
  RefreshCwIcon, 
  CircleCheckIcon, 
  TriangleAlertIcon, 
  EyeIcon, 
  EyeOffIcon 
} from '@animateicons/react/lucide';
import { LoaderIcon } from '@/components/ui/loader-icon';

export default function ApiKeysSettingsPage() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [loading, setLoading] = useState(true);
  const [themeConfig, setThemeConfig] = useState<ThemeConfig | null>(null);
  
  // Form State
  const [showAddForm, setShowAddForm] = useState(false);
  const [provider, setProvider] = useState('openai');
  const [label, setLabel] = useState('');
  const [apiKey, setApiKey] = useState('');
  const [formErrors, setFormErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  
  // Test Key State
  const [testingKeyId, setTestingKeyId] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, { status: string; message: string }>>({});

  const trashIconRefs = useRef<Record<string, any>>({});
  const refreshIconRefs = useRef<Record<string, any>>({});
  const plusIconRef = useRef<any>(null);

  useEffect(() => {
    async function loadData() {
      try {
        const [keysData, themeData] = await Promise.all([
          api.getApiKeys(),
          api.getThemeConfig()
        ]);
        setKeys(keysData);
        setThemeConfig(themeData);
      } catch (err) {
        console.error('Failed to load settings data', err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, []);

  const handleValidateAndSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setFormErrors({});
    
    if (!label.trim()) {
      setFormErrors(prev => ({ ...prev, label: 'Label is required' }));
      return;
    }
    if (!apiKey.trim()) {
      setFormErrors(prev => ({ ...prev, api_key: 'API Key is required' }));
      return;
    }

    setSubmitting(true);
    try {
      // Validate form endpoint check
      const valResult = await api.validateForm({ provider, api_key: apiKey, label });
      if (!valResult.valid) {
        setFormErrors(valResult.errors);
        setSubmitting(false);
        return;
      }

      // Create API key
      const newKey = await api.createApiKey({ provider, label, api_key: apiKey });
      setKeys(prev => [newKey, ...prev]);
      
      // Reset form
      setLabel('');
      setApiKey('');
      setProvider('openai');
      setShowAddForm(false);
    } catch (err: any) {
      console.error('Failed to add API key', err);
      const errMsg = err.response?.data?.detail || 'Failed to validate or save the API Key.';
      setFormErrors({ api_key: errMsg });
    } finally {
      setSubmitting(false);
    }
  };

  const handleDelete = async (id: string) => {
    if (!confirm('Are you sure you want to delete this API Key?')) return;
    
    trashIconRefs.current[id]?.startAnimation();
    try {
      await api.deleteApiKey(id);
      setKeys(prev => prev.filter(k => k.id !== id));
    } catch (err) {
      console.error('Failed to delete key', err);
    } finally {
      trashIconRefs.current[id]?.stopAnimation();
    }
  };

  const handleTestKey = async (id: string) => {
    setTestingKeyId(id);
    refreshIconRefs.current[id]?.startAnimation();
    
    try {
      const res = await api.testApiKey(id);
      setTestResults(prev => ({ ...prev, [id]: { status: res.status, message: res.message } }));
      
      // Refresh the key validation status locally
      setKeys(prev => prev.map(k => k.id === id ? { ...k, is_valid: res.status === 'success' } : k));
    } catch (err: any) {
      console.error('Failed to test key', err);
      const errMsg = err.response?.data?.detail || 'Connectivity test failed.';
      setTestResults(prev => ({ ...prev, [id]: { status: 'failed', message: errMsg } }));
      setKeys(prev => prev.map(k => k.id === id ? { ...k, is_valid: false } : k));
    } finally {
      setTestingKeyId(null);
      refreshIconRefs.current[id]?.stopAnimation();
    }
  };

  const getProviderIcon = (prov: string) => {
    const names: Record<string, string> = {
      openai: 'OpenAI',
      anthropic: 'Anthropic',
      gemini: 'Google Gemini',
      groq: 'Groq Llama',
      deepseek: 'DeepSeek'
    };
    return names[prov.toLowerCase()] || prov;
  };

  if (loading) {
    return (
      <div className="p-6 md:p-8 max-w-4xl mx-auto flex flex-col items-center justify-center min-h-[50vh]">
        <LoaderIcon size={24} className="text-brand mb-2 animate-spin" />
        <span className="text-sm text-muted-foreground">Loading settings...</span>
      </div>
    );
  }

  return (
    <div className="p-6 md:p-8 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-foreground flex items-center gap-2">
            <KeyIcon size={28} className="text-brand" />
            API Keys Settings
          </h1>
          <p className="mt-1 text-muted-foreground text-sm">
            Manage credentials for multi-provider LLM support (OpenAI, Claude, Groq, DeepSeek, and Gemini).
          </p>
        </div>
        <button
          onClick={() => setShowAddForm(!showAddForm)}
          onMouseEnter={() => plusIconRef.current?.startAnimation()}
          onMouseLeave={() => plusIconRef.current?.stopAnimation()}
          className="flex items-center gap-2 px-4 py-2 bg-brand text-brand-foreground hover:bg-brand-hover rounded-xl text-sm font-medium transition-colors shadow-lg shadow-brand/10 shrink-0"
        >
          <PlusIcon ref={plusIconRef} size={16} isAnimated={false} />
          Add Key
        </button>
      </div>

      {/* Add Key Form */}
      {showAddForm && (
        <div className="mb-8 p-6 rounded-xl border border-border bg-surface-1 backdrop-blur-md shadow-2xl relative overflow-hidden transition-all duration-300">
          <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-brand to-purple-500" />
          <h2 className="text-lg font-bold text-foreground mb-4">Add Encrypted API Key</h2>
          
          <form onSubmit={handleValidateAndSubmit} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Provider</label>
                <select
                  value={provider}
                  onChange={(e) => setProvider(e.target.value)}
                  className="w-full px-3 py-2 bg-surface-2 border border-border rounded-lg text-sm text-foreground focus:outline-none focus:border-brand/50 transition-colors"
                >
                  <option value="openai">OpenAI (gpt-4o-mini)</option>
                  <option value="anthropic">Anthropic (claude-3-5-haiku)</option>
                  <option value="gemini">Google Gemini (gemini-2.5-flash)</option>
                  <option value="groq">Groq (llama-3.3-70b)</option>
                  <option value="deepseek">DeepSeek (deepseek-chat)</option>
                </select>
              </div>
              
              <div>
                <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">Label (e.g. My Prod Key)</label>
                <input
                  type="text"
                  placeholder="Key Label"
                  value={label}
                  onChange={(e) => setLabel(e.target.value)}
                  className={`w-full px-3 py-2 bg-surface-2 border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors ${
                    formErrors.label ? 'border-error/50' : 'border-border'
                  }`}
                />
                {formErrors.label && (
                  <p className="mt-1 text-xs text-error">{formErrors.label}</p>
                )}
              </div>
            </div>

            <div>
              <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-1.5">API Key Value</label>
              <input
                type="password"
                placeholder="sk-proj-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className={`w-full px-3 py-2 bg-surface-2 border rounded-lg text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:border-brand/50 transition-colors ${
                  formErrors.api_key ? 'border-error/50' : 'border-border'
                }`}
              />
              {formErrors.api_key && (
                <p className="mt-1 text-xs text-error">{formErrors.api_key}</p>
              )}
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={() => setShowAddForm(false)}
                className="px-4 py-2 text-sm font-medium text-muted-foreground hover:text-foreground hover:bg-white/[0.04] rounded-lg transition-colors"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-2 bg-brand text-brand-foreground hover:bg-brand-hover disabled:opacity-50 rounded-lg text-sm font-medium transition-colors flex items-center gap-2"
              >
                {submitting && <LoaderIcon size={14} className="animate-spin" />}
                Validate & Save
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Keys List */}
      <div className="space-y-4">
        <h2 className="text-lg font-bold text-foreground">Registered API Credentials</h2>
        
        {keys.length === 0 ? (
          <div className="rounded-xl border border-border bg-surface-1 p-8 text-center backdrop-blur-md">
            <KeyIcon size={32} className="text-muted-foreground/40 mx-auto mb-3" />
            <h3 className="font-bold text-foreground">No API keys registered</h3>
            <p className="mt-1 text-sm text-muted-foreground">
              Add a key to begin using alternative models for PR reviews.
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {keys.map((key) => {
              const testResult = testResults[key.id];
              return (
                <div 
                  key={key.id}
                  className="rounded-xl border border-border bg-surface-1 p-5 transition-colors hover:border-white/[0.08] backdrop-blur-md relative"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2.5 flex-wrap">
                        <span className="font-bold text-foreground text-base">{key.label}</span>
                        <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-white/[0.04] text-muted-foreground border border-border">
                          {getProviderIcon(key.provider)}
                        </span>
                        
                        {key.is_valid !== null && (
                          <span className={`inline-flex items-center gap-1 text-xs font-medium px-2 py-0.5 rounded-full border ${
                            key.is_valid 
                              ? 'bg-success/5 border-success/20 text-success' 
                              : 'bg-error/5 border-error/20 text-error'
                          }`}>
                            {key.is_valid ? (
                              <CircleCheckIcon size={12} />
                            ) : (
                              <TriangleAlertIcon size={12} />
                            )}
                            {key.is_valid ? 'Valid' : 'Invalid'}
                          </span>
                        )}
                      </div>
                      
                      <div className="flex items-center gap-2 mt-2 text-xs font-mono text-muted-foreground">
                        <span>Masked Key: {key.masked_key}</span>
                        <span className="text-border">·</span>
                        <span>Added: {new Date(key.created_at).toLocaleDateString()}</span>
                      </div>
                    </div>

                    {/* Actions */}
                    <div className="flex items-center gap-2 shrink-0">
                      <button
                        onClick={() => handleTestKey(key.id)}
                        disabled={testingKeyId === key.id}
                        onMouseEnter={() => refreshIconRefs.current[key.id]?.startAnimation()}
                        onMouseLeave={() => refreshIconRefs.current[key.id]?.stopAnimation()}
                        className="p-2 text-muted-foreground hover:text-foreground hover:bg-white/[0.04] rounded-lg transition-colors flex items-center gap-1.5 text-xs font-semibold border border-border disabled:opacity-50"
                        title="Test key connectivity"
                      >
                        <RefreshCwIcon 
                          ref={(el) => { refreshIconRefs.current[key.id] = el; }} 
                          size={14} 
                          isAnimated={false} 
                          className={testingKeyId === key.id ? 'animate-spin text-brand' : ''}
                        />
                        {testingKeyId === key.id ? 'Testing...' : 'Test Key'}
                      </button>
                      
                      <button
                        onClick={() => handleDelete(key.id)}
                        onMouseEnter={() => trashIconRefs.current[key.id]?.startAnimation()}
                        onMouseLeave={() => trashIconRefs.current[key.id]?.stopAnimation()}
                        className="p-2 text-muted-foreground hover:text-error hover:bg-error/10 rounded-lg transition-colors border border-border"
                        title="Delete key"
                      >
                        <TrashIcon 
                          ref={(el) => { trashIconRefs.current[key.id] = el; }} 
                          size={14} 
                          isAnimated={false} 
                        />
                      </button>
                    </div>
                  </div>

                  {/* Connection Test Banner */}
                  {testResult && (
                    <div className={`mt-3 p-3 border rounded-lg text-xs flex items-start gap-2 ${
                      testResult.status === 'success'
                        ? 'bg-success/5 border-success/20 text-success'
                        : 'bg-error/5 border-error/20 text-error'
                    }`}>
                      {testResult.status === 'success' ? (
                        <CircleCheckIcon size={14} className="shrink-0 mt-0.5" />
                      ) : (
                        <TriangleAlertIcon size={14} className="shrink-0 mt-0.5" />
                      )}
                      <div>
                        <span className="font-bold uppercase tracking-wide mr-1">
                          Test {testResult.status}:
                        </span>
                        {testResult.message}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
