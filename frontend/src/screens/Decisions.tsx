import { ArrowRight, Check, Circle, Scale } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { Row, Scan } from '../types';
import { rows, text } from '../types';
import { Badge, Empty, Notice, ObligationTable, PageHeading, SectionHeading, obligationDescription } from '../components/UI';

export default function Decisions({ scan, decisions, busy, readOnly = false, onDecision }: { scan: Scan | null; decisions: Row[]; busy: boolean; readOnly?: boolean; onDecision: (payload: Row) => Promise<boolean> }) {
  const [choice, setChoice] = useState('');
  const [value, setValue] = useState('');
  const [reason, setReason] = useState('');
  const [obligation, setObligation] = useState('');
  useEffect(() => { setChoice(''); setValue(''); setReason(''); setObligation(''); }, [scan?.id]);
  const obligations = rows(scan?.analysis.obligations);
  const conflicts = rows(scan?.analysis.findings).filter(f => ['confirmed_incompatibility', 'semantic_gameplay_conflict'].includes(text(f.category)));
  const affected = obligations.filter(o => ['violated', 'unknown'].includes(text(o.state ?? o.status)));
  const canSubmit = !readOnly && !!scan && !!choice && (choice !== 'custom' || value.trim().length > 0) && reason.trim().length > 0;
  return <><PageHeading eyebrow="Design decisions / user authority" title="Make the tradeoff explicit." description="When requirements contradict each other, choose the retained behavior and review the exact waiver." />
    {readOnly && <Notice>CK3 findings are advisory. Repair design choices will become available with qualified CK3 transformation capabilities.</Notice>}
    <Notice kind="warning">A design decision authorizes a specific tradeoff. It does not establish a loading rule, remove unknown evidence, or bypass validation.</Notice>
    {!scan ? <Empty title="No pinned scan to review" detail="Scan a playset before making decisions. Approvals are bound to the source snapshot and rule profile." /> : <>
      <div className="decision-layout"><section className="panel decision-main"><div className="decision-heading"><span className="decision-icon"><Scale size={24} /></span><div><p className="eyebrow">Concrete alternatives</p><h2>{conflicts.length ? text(conflicts[0].title, 'Competing contribution requirements') : 'Record a scoped design choice'}</h2></div></div>{conflicts.length ? conflicts.map((f, i) => <p className="decision-description" key={i}>{text(f.message ?? f.description ?? f.explanation, 'Review the affected contributions before selecting an alternative.')}</p>) : <p className="decision-description">The current scan has no confirmed design contradiction. Keep unknown behavior unresolved unless you have a concrete intended design to record.</p>}
        {conflicts.length > 0 && !readOnly ? <form onSubmit={event => { event.preventDefault(); if (canSubmit) void onDecision({ scan_id: scan.id, ...(obligation ? { obligation_id: obligation } : {}), choice, ...(choice === 'custom' ? { value } : {}), reason }).then(saved => { if (saved) { setChoice(''); setReason(''); } }); }}>
          <fieldset className="choice-group"><legend>Choose an alternative</legend>{[{ id: 'A', title: 'Retain mod A’s exact requirement', description: obligations.filter(o => o.owner === 'A').map(o => obligationDescription(o)).join('; ') || 'Exact A requirements must be enumerated before a waiver can be accepted.' }, { id: 'B', title: 'Retain mod B’s exact requirement', description: obligations.filter(o => o.owner === 'B').map(o => obligationDescription(o)).join('; ') || 'Exact B requirements must be enumerated before a waiver can be accepted.' }, { id: 'custom', title: 'Specify a custom design', description: 'Record an exact value or intended outcome for review.' }].map(option => <label key={option.id} className={`choice-card ${choice === option.id ? 'choice-selected' : ''}`}><input type="radio" name="design-choice" value={option.id} checked={choice === option.id} onChange={e => setChoice(e.target.value)} /><span className="radio-visual">{choice === option.id ? <Check size={13} /> : <Circle size={13} />}</span><span><strong>{option.title}</strong><small>{option.description}</small></span></label>)}</fieldset>
          {choice === 'custom' && <label className="field">Custom value or intended outcome<input value={value} onChange={e => setValue(e.target.value)} placeholder="An exact target, such as 5" required /></label>}
          <label className="field">Scope this decision<select value={obligation} onChange={e => setObligation(e.target.value)}><option value="">Current conflict / competing exact requirements</option>{affected.map((o, i) => <option value={text(o.id)} key={i}>{obligationDescription(o)}</option>)}</select></label>
          <label className="field">Why this outcome?<textarea rows={3} value={reason} onChange={e => setReason(e.target.value)} placeholder="Describe the behavior to retain and the requirement you agree to waive." required /></label>
          <div className="decision-submit"><span>Bound to snapshot <code>{scan.id.slice(0, 12)}</code></span><button className="button primary" type="submit" disabled={!canSubmit || busy}>Save scoped decision <ArrowRight size={15} /></button></div>
          <button type="button" className="text-button keep-unresolved" onClick={() => { setChoice(''); setValue(''); setReason(''); }}>Keep unresolved</button>
        </form> : <Notice>No design decision is required for this snapshot. Inspect potential risks and unknown coverage in the investigation view.</Notice>}</section>
        <aside><section className="panel decision-aside"><SectionHeading title="What an approval changes" /><ol className="plain-steps"><li>Records the exact retained and waived requirements.</li><li>Binds your choice to the current snapshot, profile, and proposal.</li><li>Requires renewed review when those assumptions change.</li></ol><p className="muted">Unknown or violated requirements without a current waiver continue to block validated promotion.</p></section><section className="panel decision-aside"><SectionHeading title="Decision history" />{decisions.length ? decisions.map((decision, i) => <div className="decision-record" key={i}><Badge value={decision.status ?? decision.state ?? (decision.stale ? 'stale' : 'recorded')} /><strong>{text(decision.choice ?? decision.id)}</strong><p>{text(decision.reason, 'Hash-bound decision recorded.')}</p><small>{text(decision.created_at ?? decision.timestamp, '')}</small></div>) : <p className="muted">No design decisions have been recorded in this workspace.</p>}</section></aside></div>
      <SectionHeading title="Contribution ledger" /><div className="panel"><ObligationTable obligations={obligations} /></div>
    </>}
  </>;
}
