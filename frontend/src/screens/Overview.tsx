import { ArrowDown, ArrowRight, Boxes, FileSearch, ListFilter, ShieldQuestion, TriangleAlert } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { Scan, Workspace, Row } from '../types';
import { gameName, label, object, rows, text } from '../types';
import { Badge, Empty, Notice, ObligationTable, PageHeading, SectionHeading } from '../components/UI';

export default function Overview({ scan, workspace, onScan, onDiscover, onInvestigate, busy }: { scan: Scan | null; workspace: Workspace | undefined; onScan: () => void; onDiscover?: () => void; onInvestigate: (finding?: Row) => void; busy: boolean }) {
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const analysis = scan?.analysis ?? {};
  const findings = rows(analysis.findings);
  const obligations = rows(analysis.obligations);
  const files = rows(analysis.files ?? scan?.inputs);
  const definitions = rows(analysis.definitions);
  const coverage = object(analysis.coverage);
  const summary = object(analysis.summary);
  const totals = object(object(analysis.pagination).totals);
  const totalFiles = count(summary.files, totals.files, files.length);
  const totalDefinitions = count(summary.definitions, totals.definitions, definitions.length);
  const totalFindings = count(summary.findings, totals.findings, findings.length);
  const totalObligations = count(summary.obligations, totals.obligations, obligations.length);
  const loadedOpen = obligations.filter(o => ['unknown', 'violated'].includes(text(o.state ?? o.status))).length;
  const unknownCount = validCount(summary.unknown_obligations);
  const violatedCount = validCount(summary.violated_obligations);
  const summaryOpen = validCount(summary.open_obligations) ?? (unknownCount !== undefined && violatedCount !== undefined ? unknownCount + violatedCount : undefined);
  const unknowns = summaryOpen ?? loadedOpen;
  const incompleteFindings = findings.length < totalFindings;
  const incompleteObligations = obligations.length < totalObligations;
  const unavailableSources = Array.isArray(coverage.unavailable_enabled_sources) ? coverage.unavailable_enabled_sources.length : 0;
  const visible = findings.filter(item => (filter === 'all' || text(item.category) === filter) && `${text(item.display_title ?? item.title, '')} ${text(item.display_message ?? item.message, '')} ${text(item.display_target ?? item.target, '')} ${text(item.id, '')}`.toLowerCase().includes(query.toLowerCase()));
  const categories = [...new Set(findings.map(item => text(item.category, 'potential_incompatibility')))];
  const ck3 = workspace?.game_id === 'ck3';
  useEffect(() => { setFilter('all'); setQuery(''); }, [scan?.id]);
  return <><PageHeading eyebrow="Playset workspace" title="Understand the whole stack." description={ck3 ? 'Inspect CK3 source contributions, overlaps, and advisory diagnostics while preserving unknown behavior.' : 'Trace what loads, see what is lost, and preserve each mod’s contribution.'} actions={<>{onDiscover && <button className="button secondary" onClick={onDiscover} disabled={busy}><FileSearch size={16} /> Discover CK3 playsets</button>}<button className="button primary" onClick={onScan} disabled={busy || !workspace}><FileSearch size={16} /> Scan playset</button></>} />
    <div className="target-bar"><span className="target-icon"><Boxes size={20} /></span><div><strong>{workspace?.name ?? 'Your local workspace'}</strong><span>{gameName(workspace)}{workspace?.target_platform ? ` · ${workspace.target_platform === 'macos' ? 'macOS' : 'Windows'}` : ''}<span className="inline-separator">/</span>{workspace?.mode === 'game' ? 'Game snapshot' : 'Synthetic workspace'}<span className="inline-separator">/</span>{scan ? `Snapshot ${scan.id.slice(0, 12)}` : 'No snapshot captured'}</span></div><Badge value={workspace?.mode === 'game' ? 'unconfirmed' : 'synthetic'} /><span className="target-local"><span /> Local analysis</span></div>
    {ck3 && <Notice>CK3 inspection is read-only. Schema diagnostics are advisory; effective loading, automatic repairs, and runtime validation require scoped evidence for the selected build and platform.</Notice>}
    {coverage.source_inventory_complete === false && <Notice kind="warning"><strong>Source inventory is incomplete.</strong> {unavailableSources ? `${unavailableSources.toLocaleString('en-US')} enabled ${unavailableSources === 1 ? 'source was' : 'sources were'} unavailable at capture.` : 'Launcher metadata or selected sources could not be fully confirmed at capture.'} Review the discovery findings; this snapshot inspects the available content.</Notice>}
    {!scan ? <Empty title="Start with a reproducible snapshot" detail="Scan a synthetic fixture or your configured source paths. The engine records immutable inputs before it makes any loading prediction."><button className="button secondary" onClick={onScan} disabled={busy || !workspace}>Choose scan inputs <ArrowRight size={15} /></button></Empty> : <>
      <div className="stats-grid"><Metric icon={<FileSearch size={19} />} value={totalFiles} title="Source files" detail="Immutable input bytes · complete snapshot" /><Metric icon={<Boxes size={19} />} value={totalDefinitions} title="Definitions" detail="Within parser coverage · complete snapshot" /><Metric icon={<TriangleAlert size={19} />} value={totalFindings} title="Findings" detail="Across the complete snapshot" /><Metric icon={<ShieldQuestion size={19} />} value={unknowns} title="Open obligations" detail={summaryOpen === undefined && incompleteObligations ? 'Unknown or violated · loaded details only' : 'Unknown or violated · complete snapshot'} accent /></div>
      <div className="coverage-strip"><ShieldQuestion size={18} /><div><strong>Coverage is a separate result.</strong><span>{text(coverage.description ?? coverage.note, `${Object.keys(coverage).length ? 'Inspect the coverage record for supported families and unknown regions.' : 'No measured game coverage is established for this scan.'} Synthetic predictions do not verify ${ck3 ? 'CK3' : 'EU5'} behavior.`)}</span></div><button className="text-button" onClick={() => onInvestigate()}>Inspect stack <ArrowRight size={15} /></button></div>
      <SectionHeading title="Findings" detail="A predictable winner can still erase another mod’s intent."><span className="count-pill" aria-label="Loaded findings">{incompleteFindings ? `${findings.length.toLocaleString('en-US')} of ${totalFindings.toLocaleString('en-US')} loaded` : totalFindings.toLocaleString('en-US')}</span></SectionHeading>
      {incompleteFindings && <Notice>Search and category filters apply to the {findings.length.toLocaleString('en-US')} loaded findings. Categories shown here come from those entries. Use “Load more snapshot details” below to inspect more results.</Notice>}
      <div className="panel"><div className="filter-row"><div className="search-control"><ListFilter size={16} /><input aria-label="Search findings" value={query} onChange={e => setQuery(e.target.value)} placeholder={incompleteFindings ? 'Filter loaded findings…' : 'Filter findings…'} /></div><select aria-label="Finding category" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">{incompleteFindings ? 'All loaded categories' : 'All categories'}</option>{categories.map(category => <option key={category} value={category}>{label(category)}</option>)}</select></div>{visible.length ? <div className="finding-list">{visible.map((finding, i) => <button key={text(finding.display_key, `${text(finding.id, 'finding')}:${i}`)} className="finding-row" onClick={() => onInvestigate(finding)}><div className={`finding-symbol ${text(finding.category).includes('compatible_overlap') ? 'good' : ''}`}><TriangleAlert size={18} /></div><div className="finding-copy"><div><strong>{text(finding.display_title ?? finding.title ?? finding.display_target ?? finding.target ?? finding.definition_id ?? finding.kind ?? finding.id, 'Stack finding')}</strong><Badge value={finding.category} /></div><p>{text(finding.display_message ?? finding.message ?? finding.description ?? finding.explanation, 'Inspect the loading trace, source evidence, and preservation obligations.')}</p><small>{finding.severity ? `${label(finding.severity)} · ` : ''}{label(finding.certainty, 'Evidence not specified')}<span>·</span>{label(finding.impact, 'Impact not specified')}</small></div><ArrowRight size={17} /></button>)}</div> : <Empty title={totalFindings ? incompleteFindings ? 'No loaded findings match your filter' : 'No findings match your filter' : 'No findings within this scan’s coverage'} detail={incompleteFindings ? 'The remaining findings have not been loaded. Load more snapshot details to inspect additional results; the filters do not search the complete scan.' : 'Unknown or unsupported behavior remains visible in coverage. A quiet scan is not a universal compatibility guarantee.'} />}</div>
      <SectionHeading title="Preservation ledger" detail="Every contribution has its own status. A loader winner is not a waiver."><span className="count-pill" aria-label="Loaded preservation obligations">{incompleteObligations ? `${obligations.length.toLocaleString('en-US')} of ${totalObligations.toLocaleString('en-US')} loaded` : totalObligations.toLocaleString('en-US')}</span></SectionHeading>
      <div className="panel"><ObligationTable obligations={obligations} /></div>
      <div className="bottom-note"><ArrowDown size={14} /><span>Original mods remain read-only. Review and validation happen in managed staging.</span></div>
      {scan.analysis.profile && <Notice>Predictions use <strong>{text(object(scan.analysis.profile).name ?? object(scan.analysis.profile).id ?? scan.analysis.profile)}</strong>. Rule scope and evidence determine how each result may be used.</Notice>}
    </>}
  </>;
}
function Metric({ icon, value, title, detail, accent }: { icon: React.ReactNode; value: number; title: string; detail: string; accent?: boolean }) { return <div className={`metric ${accent ? 'metric-accent' : ''}`} role="group" aria-label={title}><div className="metric-top"><span>{title}</span>{icon}</div><strong>{value < 10 ? value.toString().padStart(2, '0') : value.toLocaleString('en-US')}</strong><small>{detail}</small></div>; }
function validCount(value: unknown): number | undefined { return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0 ? value : undefined; }
function count(summary: unknown, total: unknown, loaded: number): number { return validCount(summary) ?? validCount(total) ?? loaded; }
