import { useState } from 'react';
import { ArrowRight, FileSearch, RefreshCw } from 'lucide-react';
import type { Row } from '../types';
import { object, rows, text } from '../types';
import { Badge, Code, Notice, SectionHeading } from './UI';

export default function CK3Discovery({ discovery, platform, busy, onDiscover, onImport }: {
  discovery: Row; platform: string; busy: boolean;
  onDiscover: (payload: Row) => Promise<Row | null>;
  onImport: (id: string) => Promise<void>;
}) {
  const options = object(discovery.options);
  const selectedPlatform = (options.platform ?? platform) === 'windows' ? 'windows' : 'macos';
  const [steamRoots, setSteamRoots] = useState(Array.isArray(options.steam_roots) ? options.steam_roots.join('\n') : '');
  const [userData, setUserData] = useState(text(options.user_data_path, ''));
  const [installation, setInstallation] = useState(text(options.installation_path, ''));
  const [overrides, setOverrides] = useState(Object.entries(object(options.root_overrides)).map(([id, path]) => `${id} | ${text(path, '')}`).join('\n'));
  const [playset, setPlayset] = useState('');
  const [edited, setEdited] = useState(false);
  const [formError, setFormError] = useState('');
  const playsets = rows(discovery.playsets);
  const discoveredPlayset = text(discovery.selected_playset_id, '');
  const selectedPlayset = playset || discoveredPlayset;
  const sources = rows(discovery.sources);
  const diagnostics = rows(discovery.diagnostics);
  const totals = object(discovery.display_totals);
  const enabledCount = Array.isArray(discovery.playset) ? discovery.playset.length : 0;
  const sourceTotal = countTotal(totals.sources, sources.length);
  const enabledTotal = countTotal(totals.playset, enabledCount);
  const diagnosticTotal = countTotal(totals.diagnostics, diagnostics.length);
  const canImport = Boolean(discovery.id) && discovery.consistent !== false && !edited && selectedPlayset === discoveredPlayset && sources.length > 0;
  function change(action: () => void) { action(); setEdited(true); }
  async function discover() {
    setFormError('');
    const rootOverrides: Record<string, string> = {};
    for (const line of overrides.split('\n').filter(line => line.trim())) {
      const separator = line.indexOf('|');
      if (separator < 1 || !line.slice(separator + 1).trim()) { setFormError('Each root override needs a registry ID, a vertical bar, and an absolute directory.'); return; }
      rootOverrides[line.slice(0, separator).trim()] = line.slice(separator + 1).trim();
    }
    const result = await onDiscover({ platform: selectedPlatform,
      ...(steamRoots.trim() ? { steam_roots: steamRoots.split('\n').map(root => root.trim()).filter(Boolean) } : {}),
      ...(userData.trim() ? { user_data_path: userData.trim() } : {}),
      ...(installation.trim() ? { installation_path: installation.trim() } : {}),
      ...(selectedPlayset ? { playset_id: selectedPlayset } : {}),
      ...(Object.keys(rootOverrides).length ? { root_overrides: rootOverrides } : {}),
    });
    if (result) { setEdited(false); setPlayset(text(object(result.discovery).selected_playset_id, '')); }
  }
  return <>
    <Notice>Discovery reads Steam libraries, mod descriptors, and launcher playsets. Import registers read-only sources in this workspace; it does not change your launcher or activate a playset.</Notice>
    <form onSubmit={event => { event.preventDefault(); void discover(); }}>
      <label className="field">Target platform<select aria-label="Target platform" value={selectedPlatform} disabled><option value="macos">macOS</option><option value="windows">Windows</option></select><small>Use a separate workspace to inspect another target platform.</small></label>
      <details className="discovery-options"><summary>Location overrides (optional)</summary>
        <label className="field">CK3 installation directory<input value={installation} onChange={event => change(() => setInstallation(event.target.value))} placeholder="Directory containing game, binaries, and launcher" /></label>
        <label className="field">CK3 user-data directory<input value={userData} onChange={event => change(() => setUserData(event.target.value))} placeholder="Documents/Paradox Interactive/Crusader Kings III" /></label>
        <label className="field">Steam directories<textarea rows={2} value={steamRoots} onChange={event => change(() => setSteamRoots(event.target.value))} placeholder="One absolute Steam directory per line" /></label>
        <label className="field">Mod root overrides<textarea rows={3} value={overrides} onChange={event => change(() => setOverrides(event.target.value))} placeholder={'mod/ugc_123.mod | /absolute/path/to/mod'} /><small>Use the registry ID reported by discovery. Original descriptors remain unchanged.</small></label>
      </details>
      {playsets.length > 0 && <label className="field">Launcher playset<select aria-label="Launcher playset" value={selectedPlayset} onChange={event => change(() => setPlayset(event.target.value))}><option value="">Select a playset</option>{playsets.map(item => <option value={text(item.id)} key={text(item.id)}>{text(item.name ?? item.id)}{item.active === true || item.is_active === true || item.isActive === true ? ' · active in launcher' : ''}</option>)}</select><small>Discover again after changing the selection to capture its exact enabled order.</small></label>}
      {formError && <p role="alert" className="field-error">{formError}</p>}
      <div className="form-actions"><span className="muted">Original game and mod files remain read-only</span><button className="button secondary" disabled={busy}><RefreshCw size={15} /> {discovery.id ? 'Rediscover selected playset' : 'Discover CK3'}</button></div>
    </form>
    {discovery.id && <>
      <SectionHeading title="Discovered sources" detail={`${sourceTotal} available roots · ${enabledTotal} enabled mod entries`}><Badge value={discovery.complete === true ? 'captured' : 'incomplete'} /></SectionHeading>
      {sources.length < sourceTotal && <Notice>Showing {sources.length} of {sourceTotal} source roots. Import uses the complete captured selection.</Notice>}
      {enabledCount < enabledTotal && <Notice>The displayed enabled order contains {enabledCount} of {enabledTotal} mod entries. Import uses the complete captured selection.</Notice>}
      {diagnostics.length > 0 && <div className="discovery-diagnostics">{diagnostics.slice(0, 20).map((item, index) => <Notice key={index} kind={item.severity === 'error' ? 'warning' : 'info'}><strong>{text(item.code ?? item.kind, 'Discovery finding')}</strong><span> · {text(item.message ?? item.reason ?? item.description, 'Inspect the discovery record for details.')}</span></Notice>)}{diagnosticTotal > 20 && <p className="muted">Showing {Math.min(20, diagnostics.length)} of {diagnosticTotal} diagnostics. Additional entries remain retained with this discovery.</p>}</div>}
      {discovery.complete !== true && discovery.consistent !== false && <Notice kind="warning">This discovery is incomplete. Available sources can be inspected, while missing content and unresolved launcher state remain unknown.</Notice>}
      {discovery.consistent === false && <Notice kind="warning">Launcher or descriptor metadata changed during discovery. Rediscover before importing these sources.</Notice>}
      <div className="table-wrap"><table><thead><tr><th>Owner</th><th>Read-only root</th></tr></thead><tbody>{sources.map((source, index) => <tr key={index}><td>{text(source.owner)}</td><td className="mono">{text(source.path)}</td></tr>)}</tbody></table></div>
      <details className="discovery-options"><summary>Discovery provenance</summary><Code value={discovery} title="CK3 source and playset provenance" /></details>
      <div className="form-actions"><span className="muted">{edited ? 'Rediscover to capture your changed selection.' : 'Import these sources, then capture an immutable scan.'}</span><button type="button" className="button primary" disabled={busy || !canImport} onClick={() => void onImport(text(discovery.id))}><FileSearch size={15} /> Import for inspection <ArrowRight size={15} /></button></div>
    </>}
  </>;
}

function countTotal(value: unknown, displayed: number): number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= displayed ? value : displayed;
}
