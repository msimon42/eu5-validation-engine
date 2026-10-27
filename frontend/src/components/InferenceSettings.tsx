import { useEffect, useState } from 'react';
import { ArrowRight, KeyRound, ShieldCheck } from 'lucide-react';
import { object, text, type Row } from '../types';
import { Badge, Notice } from './UI';

const budgetFields = [
  { key: 'max_calls', label: 'Model requests', initial: 8, min: 1, max: 32 },
  { key: 'max_tool_calls', label: 'Tool calls', initial: 24, min: 0, max: 256 },
  { key: 'max_source_bytes', label: 'Source bytes', initial: 131072, min: 1024, max: 1048576 },
  { key: 'max_tokens', label: 'Estimated tokens', initial: 64000, min: 1024, max: 262144 },
  { key: 'max_seconds', label: 'Elapsed seconds', initial: 120, min: 1, max: 600 },
] as const;

export function liveInferenceReady(config: Row): boolean {
  return config.enabled === true && config.key_configured === true && typeof config.model === 'string' && config.model.trim().length > 0
    && Array.isArray(config.allowed_providers) && config.allowed_providers.length > 0
    && config.tools_supported === true && config.source_policy_confirmed === true && config.provider_policy_confirmed === true;
}

export default function InferenceSettings({ config, busy, onSave }: { config: Row; busy: boolean; onSave: (payload: Row) => Promise<boolean> }) {
  const [enabled, setEnabled] = useState(config.enabled === true);
  const [model, setModel] = useState(text(config.model, ''));
  const [providers, setProviders] = useState(Array.isArray(config.allowed_providers) ? config.allowed_providers.join(', ') : '');
  const [excluded, setExcluded] = useState(Array.isArray(config.excluded_patterns) ? config.excluded_patterns.join('\n') : '');
  const [toolsSupported, setToolsSupported] = useState(config.tools_supported === true);
  const [sourceConfirmed, setSourceConfirmed] = useState(config.source_policy_confirmed === true);
  const [providerConfirmed, setProviderConfirmed] = useState(config.provider_policy_confirmed === true);
  const [budgets, setBudgets] = useState<Row>(() => Object.fromEntries(budgetFields.map(field => [field.key, object(config.budgets)[field.key] ?? field.initial])));
  useEffect(() => {
    setEnabled(config.enabled === true); setModel(text(config.model, ''));
    setProviders(Array.isArray(config.allowed_providers) ? config.allowed_providers.join(', ') : '');
    setExcluded(Array.isArray(config.excluded_patterns) ? config.excluded_patterns.join('\n') : '');
    setToolsSupported(config.tools_supported === true); setSourceConfirmed(config.source_policy_confirmed === true); setProviderConfirmed(config.provider_policy_confirmed === true);
    setBudgets(Object.fromEntries(budgetFields.map(field => [field.key, object(config.budgets)[field.key] ?? field.initial])));
  }, [config]);
  const providerList = providers.split(/[,\n]/).map(value => value.trim()).filter(Boolean);
  const incomplete = enabled && (!model.trim() || providerList.length === 0 || !toolsSupported || !sourceConfirmed || !providerConfirmed);
  return <section className="inference-settings" aria-labelledby="inference-title"><div className="inference-heading"><div><p className="eyebrow">Optional remote inference</p><h3 id="inference-title">OpenRouter investigation policy</h3></div><Badge value={liveInferenceReady(config) ? 'configured' : 'disabled'} /></div>
    <p className="inference-description">Deterministic scanning and validation stay local. A live investigation sends bounded source excerpts and selected metadata to OpenRouter and your allowed provider endpoints. It may incur charges.</p>
    <div className="key-status"><KeyRound size={17} /><div><strong>{config.key_configured === true ? 'Backend API key configured' : 'Backend API key is not configured'}</strong><span>{config.key_configured === true ? 'The key stays in the backend environment and is never returned to this UI.' : 'Set OPENROUTER_API_KEY in the backend environment before launching the app. There is no browser key entry or storage.'}</span></div><Badge value={config.key_configured === true ? 'configured' : 'not_configured'} /></div>
    <form onSubmit={event => { event.preventDefault(); if (!incomplete) void onSave({ enabled, model: model.trim(), allowed_providers: providerList, excluded_patterns: excluded.split('\n').map(value => value.trim()).filter(Boolean), budgets, tools_supported: toolsSupported, source_policy_confirmed: sourceConfirmed, provider_policy_confirmed: providerConfirmed }); }}>
      <label className="policy-check policy-enable"><input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} /><span><strong>Enable remote investigations</strong><small>Replay remains the default. Each live investigation requires its own explicit start action.</small></span></label>
      <div className="policy-fields"><label className="field">OpenRouter model ID<input value={model} onChange={event => setModel(event.target.value)} placeholder="provider/model" required={enabled} autoComplete="off" /></label><label className="field">Allowed provider names<input value={providers} onChange={event => setProviders(event.target.value)} placeholder="Provider name, another allowed provider" required={enabled} autoComplete="off" /><small>Only these endpoints may be used. Unlisted fallback routing is disabled.</small></label></div>
      <label className="field">Source excerpt exclusions<textarea value={excluded} onChange={event => setExcluded(event.target.value)} rows={3} className="mono" placeholder={'private/**\nconfidential-value'} /><small>One path glob or literal exclusion per line. The backend applies exclusions to outbound context and retained transcripts, including retries.</small></label>
      <fieldset className="budget-fields"><legend>Per-investigation limits</legend>{budgetFields.map(field => <label className="field" key={field.key}>{field.label}<input type="number" min={field.min} max={field.max} step={1} required value={Number(budgets[field.key])} onChange={event => setBudgets(previous => ({ ...previous, [field.key]: Number(event.target.value) }))} /></label>)}</fieldset>
      <div className="policy-confirmations"><label className="policy-check"><input type="checkbox" checked={sourceConfirmed} onChange={event => setSourceConfirmed(event.target.checked)} /><span>I permit the bounded source excerpts and metadata from an explicitly selected snapshot to be sent under these exclusions. I understand that OpenRouter and the allowed providers receive that content.</span></label><label className="policy-check"><input type="checkbox" checked={providerConfirmed} onChange={event => setProviderConfirmed(event.target.checked)} /><span>I reviewed the allowed providers and their data handling. Requests must stay within this allowlist with unlisted fallbacks disabled.</span></label><label className="policy-check"><input type="checkbox" checked={toolsSupported} onChange={event => setToolsSupported(event.target.checked)} /><span>I verified that the selected model and provider endpoints support tool calling.</span></label></div>
      {incomplete && <p className="field-error">Enabling live inference requires an explicit model, provider allowlist, and all three policy confirmations.</p>}
      <div className="form-actions"><span className="muted"><ShieldCheck size={14} /> Local validators remain authoritative</span><button className="button primary" disabled={busy || incomplete}>Save inference policy <ArrowRight size={15} /></button></div>
    </form>
    <Notice>Models can investigate and propose bounded staging edits. They cannot waive preservation obligations, modify original mods, or activate a release.</Notice>
  </section>;
}
