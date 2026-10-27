import { useEffect, useRef, type ReactNode } from 'react';
import { AlertCircle, Check, ChevronRight, Copy, FileText, X } from 'lucide-react';
import { label, object, rows, text, type Row } from '../types';

export function Badge({ value, children, tone }: { value?: unknown; children?: ReactNode; tone?: string }) {
  const status = text(value, 'unknown').toLowerCase();
  const style = tone ?? (/^(pass|satisfied|ready|known|completed|compatible_overlap|conformed|strict_ok|validated)$/.test(status) ? 'good' : /fail|violated|confirmed_incompatibility|invalid|error/.test(status) ? 'bad' : /unknown|not_run|potential|pending|stale|blocked|documentation|conditional|unconfirmed/.test(status) ? 'warn' : /waived|design|semantic/.test(status) ? 'purple' : 'neutral');
  return <span className={`badge badge-${style}`}><span className="badge-dot" />{children ?? label(value)}</span>;
}
export function PageHeading({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description: string; actions?: ReactNode }) {
  return <div className="page-heading"><div><p className="eyebrow">{eyebrow}</p><h1>{title}</h1><p className="page-description">{description}</p></div><div className="heading-actions">{actions}</div></div>;
}
export function SectionHeading({ title, detail, children }: { title: string; detail?: string; children?: ReactNode }) {
  return <div className="section-heading"><div><h2>{title}</h2>{detail && <p>{detail}</p>}</div>{children}</div>;
}
export function Empty({ title, detail, children }: { title: string; detail: string; children?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><FileText size={25} strokeWidth={1.4} /></div><h2>{title}</h2><p>{detail}</p>{children}</div>;
}
export function Notice({ children, kind = 'info' }: { children: ReactNode; kind?: string }) {
  return <div className={`notice notice-${kind}`}><AlertCircle size={17} aria-hidden="true" /><div>{children}</div></div>;
}
export function Code({ value, title, tone }: { value: unknown; title?: string; tone?: string }) {
  const raw = text(value, 'No source text is available for this occurrence.');
  const code = raw.slice(0, 64000);
  return <div className={`code-panel ${tone ?? ''}`}>{title && <div className="code-title"><span>{title}</span><button className="icon-button" aria-label={`Copy ${title}`} onClick={() => void navigator.clipboard?.writeText(raw)}><Copy size={14} /></button></div>}<pre tabIndex={0} aria-label={title ?? 'Source text'}>{code.split('\n').map((line, index) => <span className="code-line" key={index}><span className="line-number" aria-hidden="true">{index + 1}</span><span>{line || ' '}</span></span>)}</pre>{raw.length > code.length && <p className="preview-limit">Display limited to 64,000 characters. The immutable source remains unchanged.</p>}</div>;
}
export function ObligationTable({ obligations }: { obligations: Row[] }) {
  return obligations.length ? <div className="table-wrap"><table><thead><tr><th>Contribution</th><th>Owner</th><th>Preservation</th></tr></thead><tbody>{obligations.map((item, i) => <tr key={text(item.id, String(i))}><td><strong>{obligationDescription(item)}</strong>{Boolean(item.reason) && <small>{text(item.reason)}</small>}{item.expected_value !== undefined && <small>Expected {text(item.expected_value)} · Observed {text(item.actual, 'unknown')}</small>}</td><td><span className="owner-tag">{text(item.owner ?? item.package_id)}</span></td><td><Badge value={item.state ?? item.status} /></td></tr>)}</tbody></table></div> : <p className="muted padded">No preservation obligations have been enumerated for this view.</p>;
}
export function obligationDescription(item: Row): string { return text(item.description ?? item.predicate ?? (item.field ? `${text(item.target ?? item.definition_key)} · ${text(item.field)} must equal ${text(item.expected_value ?? item.expected)}` : item.id)); }
export function GateTable({ gates }: { gates: Row[] }) {
  return <div className="table-wrap"><table className="gate-table"><thead><tr><th>Validation gate</th><th>Policy</th><th>Result</th></tr></thead><tbody>{gates.map((gate, i) => <tr key={text(gate.id, String(i))}><td><strong>{text(gate.name ?? gate.label ?? gate.id)}</strong><small>{text(gate.reason ?? gate.message ?? gate.detail, 'No additional detail')}</small></td><td>{gate.required === false ? 'Optional' : gate.required === true ? 'Required' : 'Unspecified'}</td><td><Badge value={gate.status ?? gate.outcome} /></td></tr>)}</tbody></table></div>;
}
export function KeyValues({ value }: { value: Row }) {
  return <dl className="key-values">{Object.entries(value).map(([key, val]) => <div key={key}><dt>{label(key)}</dt><dd>{typeof val === 'object' ? <pre>{text(val)}</pre> : text(val)}</dd></div>)}</dl>;
}
export function Modal({ title, description, children, onClose, wide = false }: { title: string; description?: string; children: ReactNode; onClose: () => void; wide?: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    ref.current?.focus();
    const listener = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose();
      if (event.key === 'Tab') {
        const items = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex="0"]') ?? []);
        const first = items[0]; const last = items.at(-1);
        if (event.shiftKey && (document.activeElement === first || document.activeElement === ref.current)) { event.preventDefault(); last?.focus(); }
        if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    };
    document.addEventListener('keydown', listener);
    return () => { document.removeEventListener('keydown', listener); previous?.focus(); };
  }, [onClose]);
  return <div className="modal-backdrop" onClick={event => { if (event.target === event.currentTarget) onClose(); }}><div className={`modal ${wide ? 'modal-wide' : ''}`} role="dialog" aria-modal="true" aria-labelledby="modal-title" tabIndex={-1} ref={ref}><div className="modal-heading"><div><h2 id="modal-title">{title}</h2>{description && <p>{description}</p>}</div><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={21} /></button></div>{children}</div></div>;
}
export function EvidenceDetail({ evidence }: { evidence: Row }) {
  const source = object(evidence.source);
  return <><div className="evidence-top"><Badge value={evidence.evidence_label ?? evidence.label ?? 'unknown'} /><span className="mono">{text(evidence.id)}</span></div><h3>{text(evidence.title ?? evidence.name ?? evidence.id)}</h3><p>{text(evidence.description ?? evidence.statement ?? evidence.reason, 'No explanatory statement is recorded.')}</p><KeyValues value={evidence} />{source.url && <a href={text(source.url)} target="_blank" rel="noreferrer">Open recorded source <ChevronRight size={14} /></a>}</>;
}
export function StepList({ steps }: { steps: unknown }) {
  const values = rows(steps);
  return <ol className="trace-list">{values.map((step, i) => <li key={i}><span className="trace-index">{i + 1}</span><div><strong>{text(step.mode ?? step.kind ?? step.name ?? step.phase, 'Transition')}</strong><p>{text(step.explanation ?? step.reason ?? step.description ?? step.value, 'Recorded loading transition')}</p><small className="mono">{[step.owner, step.path].filter(Boolean).map(v => text(v)).join(' · ')}</small></div></li>)}</ol>;
}
export function SuccessMark() { return <span className="success-mark"><Check size={16} /></span>; }
