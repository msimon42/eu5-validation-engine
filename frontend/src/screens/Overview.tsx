import { ArrowDown, ArrowRight, Boxes, FileSearch, ListFilter, ShieldQuestion, TriangleAlert } from 'lucide-react';
import { useState } from 'react';
import type { Scan, Workspace, Row } from '../types';
import { label, object, rows, text } from '../types';
import { Badge, Empty, Notice, ObligationTable, PageHeading, SectionHeading } from '../components/UI';

export default function Overview({ scan, workspace, onScan, onInvestigate, busy }: { scan: Scan | null; workspace: Workspace | undefined; onScan: () => void; onInvestigate: (finding?: Row) => void; busy: boolean }) {
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');
  const analysis = scan?.analysis ?? {};
  const findings = rows(analysis.findings);
  const obligations = rows(analysis.obligations);
  const files = rows(analysis.files ?? scan?.inputs);
  const definitions = rows(analysis.definitions);
  const coverage = object(analysis.coverage);
  const unknowns = obligations.filter(o => ['unknown', 'violated'].includes(text(o.state ?? o.status))).length;
  const visible = findings.filter(item => (filter === 'all' || text(item.category) === filter) && `${text(item.title, '')} ${text(item.message, '')} ${text(item.id, '')}`.toLowerCase().includes(query.toLowerCase()));
  const categories = [...new Set(findings.map(item => text(item.category, 'potential_incompatibility')))];
  return <><PageHeading eyebrow="Playset workspace" title="Understand the whole stack." description="Trace what loads, see what is lost, and preserve each mod’s contribution." actions={<button className="button primary" onClick={onScan} disabled={busy || !workspace}><FileSearch size={16} /> Scan playset</button>} />
    <div className="target-bar"><span className="target-icon"><Boxes size={20} /></span><div><strong>{workspace?.name ?? 'Your local workspace'}</strong><span>{workspace?.mode === 'game' ? 'Game snapshot' : 'Synthetic workspace'}<span className="inline-separator">/</span>{scan ? `Snapshot ${scan.id.slice(0, 12)}` : 'No snapshot captured'}</span></div><Badge value={workspace?.mode === 'game' ? 'unconfirmed' : 'synthetic'} /><span className="target-local"><span /> Local analysis</span></div>
    {!scan ? <Empty title="Start with a reproducible snapshot" detail="Scan a synthetic fixture or your configured source paths. The engine records immutable inputs before it makes any loading prediction."><button className="button secondary" onClick={onScan} disabled={busy || !workspace}>Choose scan inputs <ArrowRight size={15} /></button></Empty> : <>
      <div className="stats-grid"><Metric icon={<FileSearch size={19} />} value={files.length} title="Source files" detail="Immutable input bytes" /><Metric icon={<Boxes size={19} />} value={definitions.length} title="Definitions" detail="Within parser coverage" /><Metric icon={<TriangleAlert size={19} />} value={findings.length} title="Findings" detail="Across connected clusters" /><Metric icon={<ShieldQuestion size={19} />} value={unknowns} title="Open obligations" detail="Unknown or violated" accent /></div>
      <div className="coverage-strip"><ShieldQuestion size={18} /><div><strong>Coverage is a separate result.</strong><span>{text(coverage.description ?? coverage.note, `${Object.keys(coverage).length ? 'Inspect the coverage record for supported families and unknown regions.' : 'No measured game coverage is established for this scan.'} Synthetic predictions do not verify EU5 behavior.`)}</span></div><button className="text-button" onClick={() => onInvestigate()}>Inspect stack <ArrowRight size={15} /></button></div>
      <SectionHeading title="Findings" detail="A predictable winner can still erase another mod’s intent."><span className="count-pill">{findings.length}</span></SectionHeading>
      <div className="panel"><div className="filter-row"><div className="search-control"><ListFilter size={16} /><input aria-label="Search findings" value={query} onChange={e => setQuery(e.target.value)} placeholder="Filter findings…" /></div><select aria-label="Finding category" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">All categories</option>{categories.map(category => <option key={category} value={category}>{label(category)}</option>)}</select></div>{visible.length ? <div className="finding-list">{visible.map((finding, i) => <button key={text(finding.id, String(i))} className="finding-row" onClick={() => onInvestigate(finding)}><div className={`finding-symbol ${text(finding.category).includes('compatible_overlap') ? 'good' : ''}`}><TriangleAlert size={18} /></div><div className="finding-copy"><div><strong>{text(finding.title ?? finding.target ?? finding.definition_id ?? finding.kind ?? finding.id, 'Stack finding')}</strong><Badge value={finding.category} /></div><p>{text(finding.message ?? finding.description ?? finding.explanation, 'Inspect the loading trace, source evidence, and preservation obligations.')}</p><small>{label(finding.certainty, 'Evidence not specified')}<span>·</span>{label(finding.impact, 'Impact not specified')}</small></div><ArrowRight size={17} /></button>)}</div> : <Empty title={findings.length ? 'No findings match your filter' : 'No findings within this scan’s coverage'} detail="Unknown or unsupported behavior remains visible in coverage. A quiet scan is not a universal compatibility guarantee." />}</div>
      <SectionHeading title="Preservation ledger" detail="Every contribution has its own status. A loader winner is not a waiver." />
      <div className="panel"><ObligationTable obligations={obligations} /></div>
      <div className="bottom-note"><ArrowDown size={14} /><span>Original mods remain read-only. Review and validation happen in managed staging.</span></div>
      {scan.analysis.profile && <Notice>Predictions use <strong>{text(object(scan.analysis.profile).name ?? object(scan.analysis.profile).id ?? scan.analysis.profile)}</strong>. Rule scope and evidence determine how each result may be used.</Notice>}
    </>}
  </>;
}
function Metric({ icon, value, title, detail, accent }: { icon: React.ReactNode; value: number; title: string; detail: string; accent?: boolean }) { return <div className={`metric ${accent ? 'metric-accent' : ''}`}><div className="metric-top"><span>{title}</span>{icon}</div><strong>{value.toString().padStart(2, '0')}</strong><small>{detail}</small></div>; }
