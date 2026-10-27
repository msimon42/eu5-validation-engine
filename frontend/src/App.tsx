import { useCallback, useEffect, useRef, useState } from 'react';
import { Activity, ArrowRight, BookOpen, CheckCheck, ChevronDown, CircleHelp, Command as CommandIcon, FileSearch, FlaskConical, GitBranch, LayoutDashboard, LoaderCircle, Menu, Plus, RefreshCw, Scale, Settings2, ShieldCheck, Terminal, X } from 'lucide-react';
import { ApiError, bootstrap as fetchBootstrap, command, request } from './api';
import type { Bootstrap, Candidate, Command as CommandName, CommandResult, Job, Row, Scan, Screen, WorkspaceDetail } from './types';
import { idOf, object, rows, text } from './types';
import { Badge, Code, EvidenceDetail, KeyValues, Modal, Notice } from './components/UI';
import Overview from './screens/Overview';
import InferenceSettings from './components/InferenceSettings';
import Investigation from './screens/Investigation';
import Decisions from './screens/Decisions';
import Validation from './screens/Validation';
import Evidence from './screens/Evidence';

const navigation: { id: Screen; title: string; icon: typeof LayoutDashboard; detail: string }[] = [
  { id: 'overview', title: 'Playset overview', icon: LayoutDashboard, detail: 'Understand your stack' },
  { id: 'investigation', title: 'Investigation', icon: GitBranch, detail: 'Sources & composition' },
  { id: 'decisions', title: 'Design decisions', icon: Scale, detail: 'Review real tradeoffs' },
  { id: 'validation', title: 'Validation & release', icon: CheckCheck, detail: 'Gates & rollback' },
  { id: 'evidence', title: 'Rules & evidence', icon: BookOpen, detail: 'Scope & confidence' },
];
function newestId(items: unknown): string { return idOf(rows(items).sort((a, b) => text(b.created_at, '').localeCompare(text(a.created_at, '')))[0] ?? {}); }

export default function App() {
  const [bootstrap, setBootstrap] = useState<Bootstrap | null>(null);
  const [workspaceId, setWorkspaceId] = useState('');
  const [detail, setDetail] = useState<WorkspaceDetail | null>(null);
  const [scanId, setScanId] = useState('');
  const [scan, setScan] = useState<Scan | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [candidateId, setCandidateId] = useState('');
  const [candidate, setCandidate] = useState<Candidate | null>(null);
  const [screen, setScreen] = useState<Screen>('overview');
  const [focusId, setFocusId] = useState('');
  const [error, setError] = useState('');
  const [stale, setStale] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState('');
  const [job, setJob] = useState<Job | null>(null);
  const [notice, setNotice] = useState('');
  const [artifactId, setArtifactId] = useState('');
  const [dialog, setDialog] = useState<'workspace' | 'scan' | 'settings' | 'evidence' | 'rollback' | 'result' | null>(null);
  const [evidence, setEvidence] = useState<Row>({});
  const [result, setResult] = useState<Row>({});
  const [rollbackRelease, setRollbackRelease] = useState<Row>({});
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const refreshCounter = useRef(0);
  const [refresh, setRefresh] = useState(0);
  const resumedJobs = useRef(new Set<string>());
  const closeDialog = useCallback(() => setDialog(null), []);

  const connect = useCallback(async () => {
    setLoading(true); setError('');
    try { const data = await fetchBootstrap(); setBootstrap(data); setWorkspaceId(current => current || data.workspaces?.[0]?.id || ''); }
    catch (e) { setError(e instanceof Error ? e.message : 'Could not load the local service.'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { void connect(); }, [connect]);
  useEffect(() => {
    if (!workspaceId) { setDetail(null); setScan(null); setCandidate(null); return; }
    let cancelled = false;
    setLoading(true);
    request<WorkspaceDetail>(`/api/workspaces/${encodeURIComponent(workspaceId)}`).then(data => {
      if (cancelled) return;
      setDetail(data);
      setScanId(current => rows(data.scans).some(item => idOf(item) === current) ? current : newestId(data.scans));
      setCandidateId(current => rows(data.candidates).some(item => idOf(item) === current) ? current : newestId(data.candidates));
    }).catch(e => { if (!cancelled) setError(e.message); }).finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [workspaceId, refresh]);
  useEffect(() => {
    if (!scanId) { setScan(null); return; }
    let cancelled = false;
    request<Scan>(`/api/scans/${encodeURIComponent(scanId)}`).then(data => { if (!cancelled) setScan(data); }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [scanId, refresh]);
  useEffect(() => {
    if (!candidateId) { setCandidate(null); return; }
    let cancelled = false;
    request<Candidate>(`/api/candidates/${encodeURIComponent(candidateId)}`).then(data => { if (!cancelled) setCandidate(data); }).catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [candidateId, refresh]);
  useEffect(() => {
    if (busy) return;
    const pending = rows(detail?.jobs).find(item => ['queued', 'running'].includes(text(item.state)) && !resumedJobs.current.has(text(item.id)));
    if (!pending) return;
    const id = text(pending.id); resumedJobs.current.add(id);
    let cancelled = false;
    const resume = async () => {
      try {
        let current = await request<Job>(`/api/jobs/${encodeURIComponent(id)}`);
        while (!cancelled) {
          setJob(current);
          if (!['queued', 'running'].includes(current.state)) {
            if (current.result?.scan_id) setScanId(text(current.result.scan_id));
            if (current.result?.candidate_id) setCandidateId(text(current.result.candidate_id));
            if (current.state === 'failed') setError(text(current.error, 'The resumed job failed.'));
            refreshCounter.current += 1; setRefresh(refreshCounter.current); break;
          }
          await new Promise(resolve => setTimeout(resolve, 800));
          if (!cancelled) current = await request<Job>(`/api/jobs/${encodeURIComponent(id)}`);
        }
      } catch (e) { if (!cancelled) setError(e instanceof Error ? e.message : 'Could not reconnect to the running job.'); }
    };
    void resume();
    return () => { cancelled = true; };
  }, [detail, busy]);

  const refreshData = () => { refreshCounter.current += 1; setRefresh(refreshCounter.current); };
  async function loadMoreSnapshot() {
    if (!scan || loadingMore) return;
    setLoadingMore(true);
    try {
      const pagination = object(scan.analysis.pagination);
      const offset = Number(pagination.offset ?? 0) + Number(pagination.limit ?? 100);
      const next = await request<Scan>(`/api/scans/${encodeURIComponent(scan.id)}?offset=${offset}&limit=100`);
      setScan(previous => {
        if (!previous || previous.id !== next.id) return previous;
        const analysis = { ...next.analysis };
        for (const key of ['files', 'definitions', 'source_definitions', 'findings', 'obligations']) analysis[key] = [...rows(previous.analysis[key]), ...rows(next.analysis[key])];
        analysis.graphs = Object.fromEntries(Object.entries(object(next.analysis.graphs)).map(([key, edges]) => [key, [...rows(object(previous.analysis.graphs)[key]), ...rows(edges)]]));
        return { ...next, analysis, inputs: [...rows(previous.inputs), ...rows(next.inputs)] };
      });
    } catch (error) { setError(error instanceof Error ? error.message : 'Could not load more snapshot details.'); }
    finally { setLoadingMore(false); }
  }
  async function run(action: CommandName, payload: Row, options: { nextScreen?: Screen; keepDialog?: boolean } = {}): Promise<CommandResult | null> {
    setBusy(action); setError(''); setNotice(''); setStale(false);
    try {
      let response = await command(action, action === 'create_workspace' ? undefined : workspaceId, payload, detail?.workspace?.revision);
      if (response.job_id) {
        let current = await request<Job>(`/api/jobs/${encodeURIComponent(response.job_id)}`);
        setJob(current);
        while (['queued', 'running'].includes(current.state)) {
          await new Promise(resolve => setTimeout(resolve, 650));
          current = await request<Job>(`/api/jobs/${encodeURIComponent(current.id)}`); setJob(current);
        }
        if (current.state === 'failed') { const message = text(object(current.error).message ?? current.error, 'The job failed. Preserved evidence remains available.'); if (current.error_type === 'Conflict') throw new ApiError(message, 409, { code: 'stale_precondition' }); throw new Error(message); }
        if (current.state === 'cancelled') { setNotice('Job cancelled. Sources remain unchanged and incomplete evidence is retained.'); refreshData(); return null; }
        response = { ...response, ...current.result };
      }
      const responseWorkspace = text(response.workspace_id ?? object(response.workspace).id, '');
      if (action === 'configure_inference') { const updated = await fetchBootstrap(); setBootstrap(updated); }
      if (action === 'create_workspace') {
        const data = await fetchBootstrap(); setBootstrap(data); setWorkspaceId(responseWorkspace || data.workspaces.at(-1)?.id || ''); setScanId(''); setCandidateId(''); setScreen('overview');
      }
      if (response.scan_id) { setScanId(response.scan_id); setCandidateId(''); setCandidate(null); }
      if (response.candidate_id) { setCandidateId(response.candidate_id); if (response.candidate_id !== candidateId || action === 'validate') setArtifactId(''); }
      if (response.artifact_id) setArtifactId(response.artifact_id);
      if (action === 'rollback') { setResult(response); setDialog('rollback'); }
      else if (action === 'investigate' || action === 'backup') { setResult(response); setDialog('result'); }
      else if (!options.keepDialog) setDialog(null);
      if (options.nextScreen) setScreen(options.nextScreen);
      refreshData();
      if (action === 'investigate' && response.status === 'blocked') {
        setError(text(response.error, 'Investigation stopped at a policy or budget boundary. Retained evidence is available below.'));
        setNotice('Investigation remains unresolved. No repair or activation was authorized.');
        return response;
      }
      setNotice(action === 'configure_inference' ? 'Inference policy saved. Replay remains the default; live requests require an explicit start action.' : action === 'export' ? 'Experimental bundle created. Your active release and playset are unchanged.' : action === 'decision' ? 'Scoped decision recorded. Review the current preservation ledger and stage a new candidate.' : action === 'validate' ? 'Validation results recorded. Review every required gate before release.' : action === 'stage' ? 'Candidate created in managed staging. Review its complete preservation and validation results.' : action === 'scan' ? 'Immutable scan captured. Loading predictions and unknown coverage are ready for review.' : action === 'create_workspace' ? 'Workspace created. Choose inputs for the first snapshot.' : 'Operation recorded.');
      return response;
    } catch (e) {
      setStale(e instanceof ApiError && e.status === 409);
      setError(e instanceof Error ? e.message : 'The operation could not be completed.');
      return null;
    } finally { setBusy(''); }
  }
  const workspace = detail?.workspace ?? bootstrap?.workspaces.find(item => item.id === workspaceId);
  const page = navigation.find(item => item.id === screen)!;
  const onStage = () => { if (scan) void run('stage', { scan_id: scan.id }, { nextScreen: 'investigation' }); };
  const onValidate = () => { if (candidate) void run('validate', { candidate_id: candidate.id }, { nextScreen: 'validation' }); else setScreen('validation'); };
  const onEvidence = async (id: string) => { setEvidence({ id, status: 'loading' }); setDialog('evidence'); try { setEvidence(await request(`/api/evidence/${encodeURIComponent(id)}`)); } catch (e) { setEvidence({ id, status: 'unavailable', description: e instanceof Error ? e.message : 'No evidence was returned. Scope remains unknown.' }); } };
  const cancelJob = async () => { if (!job) return; try { await command('cancel', workspaceId, { job_id: job.id }); setNotice('Cancellation requested. The job stops at a safe boundary.'); } catch (e) { setError(e instanceof Error ? e.message : 'Cancellation failed.'); } };

  return <div className="app-shell"><a className="skip-link" href="#main-content">Skip to workspace</a><aside className={`sidebar ${sidebarOpen ? 'sidebar-open' : ''}`}>
    <div className="brand"><div className="brand-mark"><CommandIcon size={27} strokeWidth={1.5} /></div><div><strong>EU5</strong><span>MOD ENGINE</span></div><span className="brand-version">LOCAL</span></div>
    <div className="workspace-switch"><label htmlFor="workspace-select">CURRENT WORKSPACE</label><div><select id="workspace-select" aria-label="Current workspace" value={workspaceId} onChange={e => { setWorkspaceId(e.target.value); setScanId(''); setCandidateId(''); setFocusId(''); setArtifactId(''); }}><option value="" disabled>Select a workspace</option>{bootstrap?.workspaces?.map(item => <option key={item.id} value={item.id}>{item.name ?? item.id}</option>)}</select><ChevronDown size={14} /></div><button onClick={() => setDialog('workspace')}><Plus size={14} /> New workspace</button></div>
    <div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{navigation.map(item => <button key={item.id} aria-current={screen === item.id ? 'page' : undefined} className={`nav-item ${screen === item.id ? 'active' : ''}`} onClick={() => { setScreen(item.id); setSidebarOpen(false); }}><item.icon size={19} strokeWidth={1.6} /><span><strong>{item.title}</strong><small>{item.detail}</small></span>{screen === item.id && <span className="nav-active-dot" />}</button>)}</nav>
    <div className="sidebar-bottom"><div className="preservation-note"><ShieldCheck size={22} strokeWidth={1.4} /><strong>Preserve the contribution.</strong><p>Original sources are read-only. Every repair keeps its evidence.</p></div><button className="sidebar-settings" onClick={() => setDialog('settings')}><Settings2 size={17} /> Workspace & service <ArrowRight size={14} /></button><div className="service-status"><span className={bootstrap ? 'connected' : ''} />{bootstrap ? 'Local service connected' : 'Service unavailable'}<small>v{bootstrap?.version ?? '—'}</small></div></div>
  </aside>{sidebarOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} />}
    <div className="workspace-main"><header className="topbar"><button className="icon-button mobile-menu" aria-label="Open navigation" onClick={() => setSidebarOpen(true)}><Menu size={22} /></button><div className="breadcrumb">Workspace <span>/</span> <strong>{page.title}</strong></div>{rows(detail?.scans).length > 1 && <select className="snapshot-select" aria-label="Snapshot history" value={scanId} onChange={event => { setScanId(event.target.value); setArtifactId(''); setCandidateId(idOf(rows(detail?.candidates).find(item => item.scan_id === event.target.value) ?? {})); }}>{rows(detail?.scans).map(item => <option key={idOf(item)} value={idOf(item)}>{idOf(item).slice(0, 17)}{workspace?.generation === item.id ? ' · current' : ' · historical'}</option>)}</select>}<div className="topbar-right"><span className="offline-capable"><span /> Offline core</span><button className="icon-button" aria-label="Refresh workspace" onClick={() => { if (bootstrap) refreshData(); else void connect(); }}><RefreshCw size={16} className={loading ? 'spin' : ''} /></button><button className="icon-button" aria-label="Open workspace help" onClick={() => setDialog('settings')}><CircleHelp size={18} /></button><span className="user-avatar" aria-label="Local workspace">L</span></div></header>
      <main id="main-content" tabIndex={-1}>
        {error && <div className="error-banner" role="alert"><div><strong>{stale ? 'The inputs changed. Review a fresh snapshot.' : 'This operation needs attention.'}</strong><p>{error}</p></div><button className="button secondary small" onClick={() => { setError(''); if (bootstrap) refreshData(); else void connect(); }}>Reconnect / refresh</button><button className="icon-button" aria-label="Dismiss error" onClick={() => setError('')}><X size={16} /></button></div>}
        {notice && <div className="success-banner" role="status"><ShieldCheck size={17} /><span>{notice}</span><button className="icon-button" aria-label="Dismiss status" onClick={() => setNotice('')}><X size={15} /></button></div>}
        {scan && workspace?.generation && workspace.generation !== scan.id ? <Notice kind="warning">This is a historical snapshot. Its evidence remains inspectable; planning and export require the current source generation.</Notice> : null}
        {job && <div className="job-banner" role="status" aria-live="polite"><Activity size={18} className={busy ? 'pulse' : ''} /><div><strong>{text(job.phase, 'Background operation')}</strong><span>{text(job.state)}{object(job.progress).completed !== undefined ? ` · ${text(object(job.progress).completed)} / ${text(object(job.progress).total, '?')} units` : ''}</span></div>{['queued', 'running'].includes(job.state) ? <button className="button secondary small" onClick={() => void cancelJob()}>Cancel job</button> : <button className="icon-button" aria-label="Dismiss job progress" onClick={() => setJob(null)}><X size={15} /></button>}</div>}
        {loading && !bootstrap ? <div className="initial-loading"><LoaderCircle size={25} className="spin" /><p>Connecting to your local workspace…</p></div> : <>
          {screen === 'overview' && <Overview scan={scan} workspace={workspace} busy={!!busy} onScan={() => workspace ? setDialog('scan') : setDialog('workspace')} onInvestigate={finding => { setFocusId(text(finding?.definition_id ?? finding?.target, '')); setScreen('investigation'); }} />}
          {screen === 'investigation' && <Investigation scan={scan} candidate={candidate} focusId={focusId} busy={!!busy} inference={object(bootstrap?.inference)} onStage={onStage} onReplay={mode => { if (scan) void run('investigate', { scan_id: scan.id, mode }); }} onValidate={() => setScreen('validation')} />}
          {screen === 'decisions' && <Decisions scan={scan} decisions={rows(detail?.decisions)} busy={!!busy} onDecision={async payload => (await run('decision', payload)) !== null} />}
          {screen === 'validation' && <Validation scan={scan} candidate={candidate} releases={rows(detail?.releases)} busy={!!busy} onStage={onStage} onValidate={onValidate} onExport={() => { if (candidate) void run('export', { candidate_id: candidate.id, kind: 'experimental_bundle' }); }} onRollback={release => { setRollbackRelease(release); void run('rollback', { release_id: idOf(release), preview: true }, { keepDialog: true }); }} artifactId={artifactId} capabilities={bootstrap?.capabilities ?? {}} />}
          {screen === 'evidence' && <Evidence bootstrap={bootstrap} scan={scan} onEvidence={id => void onEvidence(id)} />}
          {object(scan?.analysis.pagination).has_more === true && <Notice><span>More snapshot details are available. Summary counts and coverage describe the complete scan.</span><button className="button secondary small" disabled={loadingMore} onClick={() => void loadMoreSnapshot()}>{loadingMore ? 'Loading details…' : 'Load more snapshot details'}</button></Notice>}
        </>}
        <footer className="main-footer"><span><ShieldCheck size={13} /> Local by default. Evidence for every claim.</span><span>Europa Universalis V <span>·</span> Mod compatibility workspace</span></footer>
      </main>
    </div>
    {busy && <div className="busy-indicator" aria-live="polite"><LoaderCircle size={16} className="spin" />{text(job?.phase, `${busy.charAt(0).toUpperCase()}${busy.slice(1)} in progress`)}…</div>}
    {dialog === 'workspace' && <Modal title="Create a workspace" description="Keep synthetic fixtures and private game sources separate." onClose={closeDialog}><WorkspaceForm busy={!!busy} onSubmit={payload => void run('create_workspace', payload)} /></Modal>}
    {dialog === 'scan' && <Modal title="Capture a playset snapshot" description="Inputs are read-only. The scan pins immutable bytes and an explicit order." onClose={closeDialog} wide><ScanForm bootstrap={bootstrap} workspace={object(workspace)} busy={!!busy} onSubmit={payload => void run('scan', payload, { nextScreen: 'overview' })} /></Modal>}
    {dialog === 'settings' && <Modal title="Workspace & local service" description="Inspect captured configuration and capability boundaries." onClose={closeDialog} wide><div className="settings-summary"><Terminal size={24} /><div><strong>Local engine {bootstrap?.version ?? 'unavailable'}</strong><span>The deterministic core works without remote inference.</span></div><Badge value={workspace?.mode ?? 'unconfigured'} /></div>{workspace && <KeyValues value={workspace} />}<InferenceSettings config={object(bootstrap?.inference)} busy={!!busy} onSave={async payload => (await run('configure_inference', payload, { keepDialog: true })) !== null} /><h3>Enabled capabilities</h3><Code value={bootstrap?.capabilities ?? { status: 'Local service unavailable' }} title="Service capability record" /><Notice>OpenRouter is optional and runs through bounded backend tools. Private source excerpts require a configured disclosure policy. Game validation requires a qualified Windows worker.</Notice></Modal>}
    {dialog === 'evidence' && <Modal title="Rule & source evidence" description="Recorded scope and provenance; unknown information remains unknown." onClose={closeDialog} wide><EvidenceDetail evidence={evidence} /></Modal>}
    {dialog === 'rollback' && <Modal title="Review exact rollback" description="Only application-owned changes may be restored. External edits require reconciliation." onClose={closeDialog} wide><Code value={result} title="Rollback preview" /><Notice kind="warning">Review the exact prior hashes and any intervening edits before restoration.</Notice><button className="button secondary" onClick={() => void run('rollback', { release_id: idOf(rollbackRelease), preview: false })} disabled={!!busy || result.safe === false || result.can_apply === false}>Apply managed rollback</button></Modal>}
    {dialog === 'result' && <Modal title="Investigation record" description="A local replay exercises bounded orchestration; it does not create game observations." onClose={closeDialog} wide><Code value={result} title="Recorded investigation result" /></Modal>}
  </div>;
}

function WorkspaceForm({ busy, onSubmit }: { busy: boolean; onSubmit: (payload: Row) => void }) {
  const [name, setName] = useState(''); const [mode, setMode] = useState('synthetic'); const [source, setSource] = useState(''); const [fixturePath, setFixturePath] = useState('');
  return <form onSubmit={event => { event.preventDefault(); onSubmit({ name, mode, ...(mode === 'game' && source.trim() ? { sources: parseSources(source) } : {}), ...(mode === 'synthetic' && fixturePath.trim() ? { fixture_path: fixturePath.trim() } : {}) }); }}><label className="field">Workspace name<input autoFocus placeholder="My compatibility workspace" value={name} onChange={e => setName(e.target.value)} required /></label><fieldset className="workspace-mode"><legend>Input mode</legend><label className={mode === 'synthetic' ? 'selected' : ''}><input type="radio" name="workspace-mode" value="synthetic" checked={mode === 'synthetic'} onChange={e => setMode(e.target.value)} /><FlaskConical size={20} /><strong>Synthetic</strong><span>Explore offline contract fixtures.</span></label><label className={mode === 'game' ? 'selected' : ''}><input type="radio" name="workspace-mode" value="game" checked={mode === 'game'} onChange={e => setMode(e.target.value)} /><FileSearch size={20} /><strong>Private game inputs</strong><span>Read local content without modifying it.</span></label></fieldset>{mode === 'synthetic' && <label className="field">Synthetic fixture folder (optional)<input value={fixturePath} onChange={event => setFixturePath(event.target.value)} placeholder="Absolute path to a materialized fixture folder" /><small>Leave empty for bundled cases, or import a local fixture folder containing case.json and read-only synthetic mod files. No EU5 installation is needed.</small></label>}{mode === 'game' && <><SourceInput source={source} onChange={setSource} /><Notice>Paths stay private to the local backend. Any installed EU5 version can be inspected. Choose its installation and read-only mod roots; fingerprints are captured locally. Loading semantics remain conditional until measured rules cover that build and content.</Notice></>}<div className="form-actions"><button className="button primary" disabled={busy || !name.trim() || (mode === 'game' && !source.trim())}>Create workspace <ArrowRight size={15} /></button></div></form>;
}
function ScanForm({ bootstrap, workspace, busy, onSubmit }: { bootstrap: Bootstrap | null; workspace: Row; busy: boolean; onSubmit: (payload: Row) => void }) {
  const fixtures = (bootstrap?.fixtures ?? []).map(item => typeof item === 'string' ? { id: item, name: item } : item);
  const [mode, setMode] = useState(workspace.mode === 'game' ? 'sources' : 'fixture');
  const [fixture, setFixture] = useState(text(fixtures.find(f => f.id === 'F03' || text(f.id).includes('003'))?.id ?? fixtures[0]?.id, '003-disjoint-properties'));
  const [source, setSource] = useState(rows(workspace.sources).map(item => `${text(item.owner, 'A')} | ${text(item.path, '')}`).join('\n'));
  const [order, setOrder] = useState(rows(workspace.sources).filter(item => item.owner !== 'V').map(item => text(item.owner, '')).join(', ') || 'A, B'); const [json, setJson] = useState(''); const [jsonError, setJsonError] = useState('');
  const [profile, setProfile] = useState('synthetic-contract-v1');
  if (workspace.fixture_path) return <form onSubmit={event => { event.preventDefault(); onSubmit({}); }}><label className="field">Synthetic fixture folder<input value={text(workspace.fixture_path)} readOnly /></label><Notice>The backend reads the actual files from this registered folder, verifies the pinned manifest and author baselines, and preserves the source bytes. This workspace cannot activate a real game playset.</Notice><SourceInput source={source} onChange={setSource} readOnly /><div className="form-actions"><span className="muted"><ShieldCheck size={14} /> Read-only disk inputs · synthetic contract</span><button className="button primary" disabled={busy}>Capture & scan <FileSearch size={15} /></button></div></form>;
  return <form onSubmit={event => { event.preventDefault(); setJsonError(''); if (mode === 'fixture') onSubmit({ fixture_id: fixture }); else if (mode === 'sources') onSubmit({ playset: order.split(',').map(v => v.trim()).filter(Boolean), ...(workspace.mode !== 'game' ? { profile_id: profile } : {}) }); else { try { const payload = JSON.parse(json); if (!payload || typeof payload !== 'object' || !Array.isArray(payload.inputs)) throw new Error('Provide an object with an inputs array and playset.'); onSubmit(payload); } catch (e) { setJsonError(e instanceof Error ? e.message : 'Invalid JSON.'); } } }}><div className="tab-strip form-tabs" role="tablist" aria-label="Scan input source">{[['fixture', 'Contract fixture'], ['sources', 'Private source paths'], ['json', 'Manifest JSON']].map(([id, name]) => <button type="button" role="tab" aria-selected={mode === id} key={id} onClick={() => setMode(id)}>{name}</button>)}</div>{mode === 'fixture' ? <><label className="field">Fixture<select value={fixture} onChange={e => setFixture(e.target.value)}>{fixtures.length ? fixtures.map((item, i) => <option value={text(item.id)} key={i}>{text(item.name ?? item.title ?? item.id)}</option>) : <option value="003-disjoint-properties">003 — Disjoint properties</option>}</select></label><Notice>Synthetic fixtures test the application’s declared contract. They are not EU5 observations and cannot activate a real playset.</Notice></> : mode === 'sources' ? <><SourceInput source={source} onChange={setSource} readOnly /><label className="field">Enabled playset order<input value={order} onChange={e => setOrder(e.target.value)} placeholder="A, B" /><small>Comma-separated owner IDs. Keep the vanilla baseline separate from enabled mods.</small></label>{workspace.mode !== 'game' && <label className="field">Explicit rule profile<input value={profile} onChange={e => setProfile(e.target.value)} required /></label>}<Notice>The scan uses the private roots registered when this workspace was created. Create a private game workspace to add source paths. The backend enforces containment, snapshot consistency, and build/profile scope.</Notice></> : <><label className="field">Exact fixture or input manifest<textarea className="mono" rows={12} value={json} onChange={e => setJson(e.target.value)} placeholder={'{ "inputs": [{ "owner": "A", "path": "in_game/common/testdb/10.txt", "bytes_base64": "aXRlbSA9IHsgeCA9IDIgfQo=" }], "playset": ["A"], "profile_id": "synthetic-contract-v1" }'} required /></label>{jsonError && <p role="alert" className="field-error">{jsonError}</p>}</>}<div className="form-actions"><span className="muted"><ShieldCheck size={14} /> Original files remain read-only</span><button className="button primary" disabled={busy || (mode === 'sources' && !source.trim())}>Capture & scan <FileSearch size={15} /></button></div></form>;
}
function SourceInput({ source, onChange, readOnly = false }: { source: string; onChange: (value: string) => void; readOnly?: boolean }) { return <label className="field">Explicit private source paths<textarea aria-label="Explicit private source paths" value={source} readOnly={readOnly} onChange={e => onChange(e.target.value)} rows={5} className="mono" placeholder={'V | /path/to/private/vanilla/game\nA | /path/to/private/mod-a\nB | /path/to/private/mod-b'} required /><small>One source per line: owner ID, a vertical bar, and an absolute directory. No files are uploaded to a remote service by a scan.</small></label>; }
function parseSources(value: string): Row[] { return value.split('\n').filter(line => line.trim()).map((line, index) => { const separator = line.indexOf('|'); return separator >= 0 ? { owner: line.slice(0, separator).trim(), path: line.slice(separator + 1).trim() } : { owner: String.fromCharCode(65 + index), path: line.trim() }; }); }
