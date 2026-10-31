import { ArrowRight, FileCode2, GitBranch, Layers3, Search, WandSparkles } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { Candidate, Row, Scan } from '../types';
import { idOf, object, rows, text } from '../types';
import { liveInferenceReady } from '../components/InferenceSettings';
import { Badge, Code, Empty, Notice, ObligationTable, PageHeading, SectionHeading, StepList } from '../components/UI';

export default function Investigation({ scan, candidate, focusId, busy, readOnly = false, inference, onStage, onReplay, onValidate }: { scan: Scan | null; candidate: Candidate | null; focusId: string; busy: boolean; readOnly?: boolean; inference: Row; onStage: () => void; onReplay: (mode: 'replay' | 'live') => void; onValidate: () => void }) {
  const definitions = rows(scan?.analysis.definitions);
  const files = rows(scan?.analysis.files ?? scan?.inputs);
  const [selectedId, setSelectedId] = useState('');
  const [query, setQuery] = useState('');
  const [definitionPage, setDefinitionPage] = useState(0);
  const [view, setView] = useState('sources');
  const [mode, setMode] = useState<'replay' | 'live'>('replay');
  const liveReady = liveInferenceReady(inference);
  useEffect(() => { if (!liveReady) setMode('replay'); }, [liveReady]);
  useEffect(() => { setDefinitionPage(0); }, [query, scan?.id]);
  const matchingDefinitions = definitions.filter(d => `${text(d.name, '')} ${text(d.key ?? d.id, '')}`.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => { setSelectedId(focusId || text(definitions[0]?.key ?? definitions[0]?.id, '')); }, [scan?.id, focusId]); // definition ids belong to the scan snapshot
  const selected = definitions.find(d => text(d.key ?? d.id, '') === selectedId) ?? definitions[0];
  const trace = selected?.operations ?? selected?.transitions ?? scan?.analysis.transitions;
  const allObligations = rows(view === 'candidate' && candidate ? candidate.validation?.obligations ?? candidate.plan.obligations : scan?.analysis.obligations);
  const obligations = allObligations.filter(o => !(o.definition_id ?? o.target) || !selected || (o.definition_id ?? o.target) === (selected.key ?? selected.id));
  const patchFiles = rows(candidate?.plan?.files);
  const sourceIds = new Set(rows(scan?.analysis.source_definitions).filter(record => record.key === (selected?.key ?? selected?.id)).map(record => text(record.file_id)));
  const scopedFiles = sourceIds.size ? files.filter(file => sourceIds.has(text(file.id))) : files;
  const relevantFiles: Row[] = (selected && Array.isArray(selected.sources) ? rows(selected.sources) : scopedFiles).slice(0, 24).map(file => {
    const input = rows(scan?.inputs).find(input => input.owner === file.owner && input.path === file.path);
    return { ...file, preview_only: input?.preview_only, text: file.text ?? sourcePreview(input ?? file) };
  });
  return <><PageHeading eyebrow="Investigation / source provenance" title="Every change has a history." description="Follow file selection, ordered operations, and readers back to the original contribution." actions={<><select aria-label="Investigation mode" className="investigation-mode" value={mode} disabled={readOnly} onChange={event => setMode(event.target.value as 'replay' | 'live')}><option value="replay">Offline replay</option><option value="live" disabled={!liveReady}>Live OpenRouter{!liveReady ? ' · configure policy first' : ''}</option></select><button className="button secondary" disabled={readOnly || !scan || busy || (mode === 'live' && !liveReady)} onClick={() => onReplay(mode)}><WandSparkles size={16} /> {mode === 'live' ? 'Start live investigation' : 'Replay investigation'}</button><button className="button primary" disabled={readOnly || !scan || busy} onClick={onStage}><Layers3 size={16} /> Stage proposal</button></>} />
    {readOnly && <Notice>CK3 source inspection preserves all contributions. Automatic staging and agent-driven proposals remain unavailable until CK3 loading and transformation capabilities are qualified.</Notice>}
    {mode === 'live' && <Notice kind="warning">Starting this investigation sends bounded source excerpts, findings, selected definition metadata, and rule evidence from this snapshot to OpenRouter using <strong>{text(inference.model)}</strong>. Allowed providers: <strong>{Array.isArray(inference.allowed_providers) ? inference.allowed_providers.join(', ') : 'none'}</strong>. Exclusions and per-job budgets apply to requests and retained transcripts. A model proposal still requires local validation.</Notice>}
    {!scan ? <Empty title="Capture a scan first" detail="A pinned snapshot gives every explanation and edit an exact source identity." /> : <>
      <Notice>Loading predictions and preservation are separate. Unknown readers, missing ancestry, or dynamic references can block an otherwise parseable proposal.</Notice>
      <div className="investigation-layout"><aside className="definition-sidebar panel"><div className="definition-title"><GitBranch size={17} /><strong>Definitions</strong><span className="count-pill">{definitions.length}</span></div><div className="definition-search"><Search size={15} /><input aria-label="Search definitions" placeholder="Find a definition…" value={query} onChange={e => setQuery(e.target.value)} /></div><div className="definition-list">{matchingDefinitions.slice(definitionPage * 100, (definitionPage + 1) * 100).map((definition, i) => <button key={idOf(definition) || i} className={definition === selected ? 'selected' : ''} onClick={() => setSelectedId(text(definition.key ?? definition.id, ''))}><FileCode2 size={16} /><span><strong>{text(definition.name ?? definition.key ?? definition.id, 'Definition')}</strong><small>{text(definition.family, 'Family unknown')}</small></span></button>)}</div>{matchingDefinitions.length > 100 && <div className="inline-actions"><button className="text-button" disabled={definitionPage === 0} onClick={() => setDefinitionPage(page => page - 1)}>Previous definitions</button><span>{definitionPage + 1} / {Math.ceil(matchingDefinitions.length / 100)}</span><button className="text-button" disabled={(definitionPage + 1) * 100 >= matchingDefinitions.length} onClick={() => setDefinitionPage(page => page + 1)}>Next definitions</button></div>}</aside>
        <div className="investigation-main"><div className="panel"><div className="definition-detail-heading"><div><p className="eyebrow">{text(selected?.stage, 'Stage retained in source paths')}</p><h2>{text(selected?.name ?? selected?.key ?? selected?.id, 'Source stack')}</h2></div><Badge value={selected?.certainty ?? 'conditional'} /></div><div className="tab-strip" role="tablist" aria-label="Definition views">{[['sources', 'Source contributions'], ['effective', 'Effective result'], ['candidate', 'Staged diff']].map(([id, name]) => <button key={id} id={`tab-${id}`} role="tab" aria-selected={view === id} aria-controls={`panel-${id}`} onClick={() => setView(id)}>{name}</button>)}</div>
          <div className="view-content" role="tabpanel" id={`panel-${view}`} aria-labelledby={`tab-${view}`}>
            {view === 'sources' && <><div className="source-grid">{relevantFiles.length ? relevantFiles.map((file, i) => <SourceFile file={file} key={`${text(file.owner)}-${text(file.path)}-${i}`} />) : <Code value={selected?.body ?? selected?.text} title="Original source" />}</div>{scopedFiles.length > 24 && <Notice>Showing 24 source files. Select a definition to narrow the source dependency scope.</Notice>}</>}
            {view === 'effective' && <><Code value={readOnly ? { state: selected?.state ?? 'unknown', reason: 'CK3 family loading and field readers are not qualified.', provenance: selected?.provenance } : selected?.value ?? selected?.effective ?? selected?.body ?? scan.analysis.effective} title={readOnly ? "Unconfirmed effective result" : "Effective value under the selected profile"} /><Notice>Presence in an effective body does not prove that the field reader executes every occurrence.</Notice></>}
            {view === 'candidate' && (candidate ? <>{patchFiles.length ? patchFiles.map((file, i) => <div key={i} className="diff-pair"><Code value={file.before_text ?? file.before ?? 'New managed file'} title={text(file.path, 'Generated file') + ' · before'} tone="before" /><Code value={file.text ?? file.after_text ?? file.content} title="Staged output" tone="after" /></div>) : <Empty title="No generated file in this candidate" detail={text(candidate.plan.reason ?? candidate.plan.disposition, 'Review the candidate’s obligations and blockers.')} />}<div className="inline-actions"><Badge value={candidate.status} /><button className="text-button" onClick={onValidate}>Review full-stack validation <ArrowRight size={15} /></button></div></> : <Empty title="Review a concrete staged composition" detail="The deterministic planner checks ancestry, reader semantics and all affected contributions before it proposes a managed output."><button className="button secondary" onClick={onStage} disabled={readOnly || busy}>Stage proposal</button></Empty>)}
          </div></div>
          <div className="panel trace-panel"><SectionHeading title="Loading trace" detail="Source order and operation class both matter." />{rows(trace).length ? <StepList steps={trace} /> : <div className="trace-empty"><GitBranch size={20} /><p>No ordered transitions were recorded for this selection. Inspect the complete analysis below.</p></div>}<details><summary>Raw definition and provenance</summary><Code value={selected ?? scan.analysis} title="Pinned analysis record" /></details></div>
        </div></div>
      <SectionHeading title="Affected preservation obligations" detail="Satisfied, violated, unknown, and narrowly waived contributions remain visible." /><div className="panel"><ObligationTable obligations={obligations} /></div>
    </>}
  </>;
}
function SourceFile({ file }: { file: Row }) { const metadata = object(file.source); return <div className="source-card"><div className="source-owner"><span className="owner-tag">{text(file.owner ?? metadata.owner, 'Source')}</span>{(file.shadowed === true || Boolean(file.shadowed_by) || file.active === false) && <Badge value={file.shadowed_by || file.shadowed ? 'shadowed' : 'inactive'} />}<span className="mono">{text(file.sha256 ?? file.hash, 'Hash retained in snapshot').slice(0, 16)}</span></div><Code value={file.text ?? file.content ?? file.body ?? file.source_text} title={text(file.path ?? file.relative_path, 'Source file')} /></div>; }
function sourcePreview(input: Row): string {
  if (typeof input.bytes_base64 !== 'string') return text(input.snippet ?? input.content, 'No source preview is available. Exact bytes remain in the source snapshot.');
  try {
    const binary = atob(input.bytes_base64.slice(0, 87384));
    const bytes = Uint8Array.from(binary, char => char.charCodeAt(0));
    const truncated = input.preview_only === true || input.bytes_base64.length > 87384;
    const decoded = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes, { stream: truncated });
    return decoded + (truncated ? '\n[Bounded source preview. Exact bytes and hashes remain in the immutable snapshot.]' : '');
  } catch { return `Opaque or unsupported encoding. Exact bytes are preserved.\nBase64 preview:\n${input.bytes_base64.slice(0, 2048)}`; }
}
