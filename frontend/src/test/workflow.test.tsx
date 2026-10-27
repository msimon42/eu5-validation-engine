import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import type { Row } from '../types';

const source = { owner: 'A', path: 'in_game/common/testdb/a.txt', text: 'REPLACE:item = { x = 2 y = 1 }\n', sha256: 'a'.repeat(64) };
const scan = { id: 'scan-1', workspace_id: 'workspace-1', created_at: '2026-10-27T12:00:00Z', analysis: {
  summary: {}, files: [source], definitions: [{ id: 'testdb/item', family: 'testdb', stage: 'in_game', value: { x: '1', y: '3' }, operations: [{ mode: 'REPLACE', owner: 'A', path: source.path, explanation: 'A replaces x.' }, { mode: 'REPLACE', owner: 'B', explanation: 'B erases A’s x change.' }] }],
  findings: [{ id: 'finding-1', title: 'Independent field changes are shadowed', category: 'potential_incompatibility', message: 'B’s replacement erases A’s x contribution.', certainty: 'P', definition_id: 'testdb/item' }],
  obligations: [{ id: 'obligation-A', owner: 'A', description: 'item.x must remain 2', state: 'violated' }, { id: 'obligation-B', owner: 'B', description: 'item.y must remain 3', state: 'satisfied' }], coverage: { description: 'Synthetic testdb only; actual EU5 loading remains unconfirmed.' }, profile: { id: 'synthetic-contract-v1', profile_kind: 'synthetic', production_export_enabled: false },
} };
const candidate = { id: 'candidate-1', status: 'staged', scan_id: 'scan-1', plan: { files: [{ path: 'in_game/common/testdb/zz_compat.txt', text: 'REPLACE:item = { x = 2 y = 3 }\n' }], obligations: [{ id: 'A', owner: 'A', description: 'item.x == 2', state: 'satisfied' }] }, validation: { experimental_eligible: true, gates: [{ id: 'syntax', name: 'Supported syntax', required: true, status: 'pass' }, { id: 'runtime', name: 'Game observations', required: true, status: 'not_run', reason: 'No game run was executed.' }] } };

function server(options: { initialScan?: boolean; initialCandidate?: boolean; conflict?: boolean; stale?: boolean; keyConfigured?: boolean; inference?: Row } = {}) {
  let scanned = options.initialScan ?? false;
  let staged = options.initialCandidate ?? false;
  let validated = options.initialCandidate ?? false;
  let inference: Row = { enabled: false, model: '', allowed_providers: [], excluded_patterns: [], budgets: { max_calls: 8, max_tool_calls: 24, max_source_bytes: 131072, max_tokens: 64000, max_seconds: 120 }, tools_supported: false, source_policy_confirmed: false, provider_policy_confirmed: false, ...options.inference, key_configured: options.keyConfigured ?? false };
  const commands: Row[] = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });
    if (path === '/api/bootstrap') return json({ session_token: 'private-session-token', version: '0.1.0', workspaces: [{ id: 'workspace-1', name: 'Synthetic lab', mode: 'synthetic' }], fixtures: [{ id: '003-disjoint-properties', name: '003 — Disjoint properties' }], profiles: [{ id: 'synthetic-contract-v1', name: 'Synthetic contract', evidence_label: 'P' }], experiments: [{ id: 'E01', name: 'Path selection', status: 'not_run' }], inference, capabilities: { production_export_enabled: false } });
    if (path === '/api/workspaces/workspace-1') return json({ workspace: { id: 'workspace-1', name: 'Synthetic lab', mode: 'synthetic', revision: 7 }, scans: scanned ? [{ id: 'scan-1' }] : [], candidates: staged ? [{ id: 'candidate-1' }] : [], releases: [], decisions: [], jobs: [] });
    if (path === '/api/scans/scan-1') return json(options.conflict ? { ...scan, analysis: { ...scan.analysis, findings: [{ id: 'conflict', title: 'Competing exact values', category: 'confirmed_incompatibility', message: 'A requires x2 and B requires x5.' }] } } : scan);
    if (path === '/api/candidates/candidate-1') return json({ ...candidate, validation: validated ? candidate.validation : undefined });
    if (path.startsWith('/api/evidence/')) return json({ id: 'synthetic-contract-v1', label: 'P', description: 'Proposed contract; no executed game observations.' });
    if (path === '/api/commands') {
      const body = JSON.parse(String(init?.body)); commands.push(body);
      expect(new Headers(init?.headers).get('X-Session-Token')).toBe('private-session-token');
      expect(init?.credentials).toBe('same-origin');
      if (options.stale) return json({ detail: { message: 'The source hash changed.' } }, 409);
      if (body.command === 'scan') { scanned = true; return json({ scan_id: 'scan-1' }); }
      if (body.command === 'stage') { staged = true; return json({ candidate_id: 'candidate-1' }); }
      if (body.command === 'validate') { validated = true; return json({ candidate_id: 'candidate-1' }); }
      if (body.command === 'export') return json({ artifact_id: 'artifact-1' });
      if (body.command === 'configure_inference') { inference = { ...body.payload, key_configured: options.keyConfigured ?? false }; return json({ configured: true }); }
      return json({ recorded: true });
    }
    return json({ detail: `Unexpected route ${path}` }, 404);
  });
  vi.stubGlobal('fetch', fetchMock);
  return { commands, fetchMock };
}
beforeEach(() => vi.restoreAllMocks());
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('local workspace workflows', () => {
  it('scans, stages and exports an explicitly inactive experimental bundle through authenticated commands', async () => {
    const { commands } = server(); const user = userEvent.setup(); render(<App />);
    await screen.findByText('Start with a reproducible snapshot');
    await user.click(screen.getByRole('button', { name: 'Scan playset' }));
    await user.click(screen.getByRole('button', { name: 'Capture & scan' }));
    await screen.findByText('Independent field changes are shadowed');
    expect(commands[0]).toMatchObject({ command: 'scan', workspace_id: 'workspace-1', expected_revision: 7, payload: { fixture_id: '003-disjoint-properties' } });
    await user.click(screen.getByText('Independent field changes are shadowed'));
    expect(await screen.findByText('Every change has a history.')).toBeVisible();
    expect(screen.getByText('B erases A’s x change.')).toBeVisible();
    await user.click(screen.getByRole('button', { name: 'Stage proposal' }));
    await waitFor(() => expect(commands.some(c => c.command === 'stage')).toBe(true));
    await user.click(screen.getByRole('button', { name: /Validation & release/ }));
    await screen.findByText('candidate-1');
    expect(screen.getByRole('button', { name: 'Promotion unavailable' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Export experimental bundle' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: 'Validate full playset' }));
    await screen.findByText('Not Run');
    await waitFor(() => expect(screen.getByRole('button', { name: 'Export experimental bundle' })).toBeEnabled());
    await user.click(screen.getByRole('button', { name: 'Export experimental bundle' }));
    const download = await screen.findByRole('link', { name: 'Download bundle' });
    expect(download).toHaveAttribute('href', '/api/artifacts/artifact-1');
    expect(commands.find(c => c.command === 'export')).toMatchObject({ payload: { candidate_id: 'candidate-1', kind: 'experimental_bundle' } });
    expect(screen.getByText(/Your active release and playset are unchanged/)).toBeVisible();
  });

  it('never preselects a lossy design choice and sends a snapshot-bound, explained decision', async () => {
    const { commands } = server({ initialScan: true, conflict: true }); const user = userEvent.setup(); render(<App />);
    await screen.findByText('Competing exact values');
    await user.click(screen.getByRole('button', { name: /Design decisions/ }));
    const radios = screen.getAllByRole('radio');
    radios.forEach(radio => expect(radio).not.toBeChecked());
    const save = screen.getByRole('button', { name: 'Save scoped decision' }); expect(save).toBeDisabled();
    await user.click(screen.getByRole('radio', { name: /Retain mod B/ }));
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText('Why this outcome?'), 'Use B’s exact balance target and waive A’s competing value.');
    await user.click(save);
    await waitFor(() => expect(commands.some(c => c.command === 'decision')).toBe(true));
    expect(commands.find(c => c.command === 'decision')).toMatchObject({ payload: { scan_id: 'scan-1', choice: 'B', reason: 'Use B’s exact balance target and waive A’s competing value.' }, expected_revision: 7 });
  });

  it('keeps failed stale mutations visible and does not claim a successful stage', async () => {
    const { commands } = server({ initialScan: true, stale: true }); const user = userEvent.setup(); render(<App />);
    await screen.findByText('Independent field changes are shadowed');
    await user.click(screen.getByRole('button', { name: /Investigation/ }));
    await user.click(screen.getByRole('button', { name: 'Stage proposal' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('The source hash changed.');
    expect(screen.getByRole('alert')).toHaveTextContent('The inputs changed.');
    expect(commands).toHaveLength(1);
    expect(screen.queryByText('Candidate created in managed staging.')).not.toBeInTheDocument();
  });

  it('shows actual service unavailability rather than inventing a populated workspace', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline'))); render(<App />);
    expect(await screen.findByRole('alert')).toHaveTextContent('The local service is unavailable.');
    expect(screen.getByText(/No snapshot captured/)).toBeVisible();
    expect(screen.queryByText('Independent field changes are shadowed')).not.toBeInTheDocument();
  });

  it('registers explicit private roots only on game workspace creation', async () => {
    const { commands } = server(); const user = userEvent.setup(); render(<App />);
    await screen.findByText('Start with a reproducible snapshot');
    await user.click(screen.getByRole('button', { name: 'New workspace' }));
    const dialog = screen.getByRole('dialog');
    await user.type(within(dialog).getByLabelText('Workspace name'), 'Private test stack');
    await user.click(within(dialog).getByRole('radio', { name: /Private game inputs/ }));
    await user.type(within(dialog).getByLabelText('Explicit private source paths'), 'V | /private/game\nA | /private/mod-a');
    await user.click(within(dialog).getByRole('button', { name: 'Create workspace' }));
    await waitFor(() => expect(commands.some(c => c.command === 'create_workspace')).toBe(true));
    expect(commands.find(c => c.command === 'create_workspace')).toMatchObject({ payload: { name: 'Private test stack', mode: 'game', sources: [{ owner: 'V', path: '/private/game' }, { owner: 'A', path: '/private/mod-a' }] } });
  });

  it('saves an explicit inference policy without credentials and keeps replay as the default', async () => {
    const { commands } = server({ initialScan: true, keyConfigured: true });
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Independent field changes are shadowed');
    await user.click(screen.getByRole('button', { name: 'Workspace & service' }));
    const dialog = screen.getByRole('dialog');
    expect(within(dialog).getByText('Backend API key configured')).toBeVisible();
    expect(within(dialog).queryByRole('textbox', { name: /API key/i })).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole('checkbox', { name: /Enable remote investigations/ }));
    const save = within(dialog).getByRole('button', { name: 'Save inference policy' });
    expect(save).toBeDisabled();
    await user.type(within(dialog).getByLabelText('OpenRouter model ID'), 'provider/test-model');
    await user.type(within(dialog).getByRole('textbox', { name: /Allowed provider names/ }), 'Provider Alpha, Provider Beta');
    await user.type(within(dialog).getByRole('textbox', { name: /Source excerpt exclusions/ }), 'private/**\nconfidential-value');
    await user.click(within(dialog).getByRole('checkbox', { name: /I permit the bounded source excerpts/ }));
    await user.click(within(dialog).getByRole('checkbox', { name: /I reviewed the allowed providers/ }));
    await user.click(within(dialog).getByRole('checkbox', { name: /I verified that the selected model/ }));
    await user.click(save);
    await waitFor(() => expect(commands.some(c => c.command === 'configure_inference')).toBe(true));
    const saved = commands.find(c => c.command === 'configure_inference');
    expect(saved).toMatchObject({ command: 'configure_inference', payload: { enabled: true, model: 'provider/test-model', allowed_providers: ['Provider Alpha', 'Provider Beta'], excluded_patterns: ['private/**', 'confidential-value'], source_policy_confirmed: true, provider_policy_confirmed: true, tools_supported: true, budgets: { max_calls: 8, max_tool_calls: 24, max_source_bytes: 131072, max_tokens: 64000, max_seconds: 120 } } });
    expect(JSON.stringify(saved)).not.toContain('api_key');
    await screen.findByText('Inference policy saved. Replay remains the default; live requests require an explicit start action.');
    await user.click(within(dialog).getByRole('button', { name: 'Close dialog' }));
    await user.click(screen.getByRole('button', { name: /Investigation/ }));
    const mode = screen.getByRole('combobox', { name: 'Investigation mode' });
    expect(mode).toHaveValue('replay');
    await user.selectOptions(mode, 'live');
    expect(screen.getByRole('button', { name: 'Start live investigation' })).toBeEnabled();
    expect(screen.getByText(/Starting this investigation sends bounded source excerpts/)).toBeVisible();
    expect(commands.some(c => c.command === 'investigate')).toBe(false);
  });

  it('keeps live inference unavailable without a backend key even when the saved policy is complete', async () => {
    server({ initialScan: true, keyConfigured: false, inference: { enabled: true, model: 'provider/test-model', allowed_providers: ['Provider Alpha'], source_policy_confirmed: true, provider_policy_confirmed: true, tools_supported: true } });
    const user = userEvent.setup(); render(<App />);
    await screen.findByText('Independent field changes are shadowed');
    await user.click(screen.getByRole('button', { name: /Investigation/ }));
    expect(screen.getByRole('option', { name: /Live OpenRouter/ })).toBeDisabled();
    expect(screen.getByRole('combobox', { name: 'Investigation mode' })).toHaveValue('replay');
    await user.click(screen.getByRole('button', { name: 'Workspace & service' }));
    expect(screen.getByText(/Set OPENROUTER_API_KEY in the backend environment before launching/)).toBeVisible();
  });
});
