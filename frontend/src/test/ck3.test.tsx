import { cleanup, render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from '../App';
import type { Row } from '../types';

const ck3Scan = { id: 'ck3-scan', workspace_id: 'ck3-workspace', analysis: {
  profile: { id: 'ck3-advisory-v1', game_id: 'ck3', profile_kind: 'documentation_only', production_export_enabled: false },
  files: [], definitions: [], obligations: [], coverage: { description: 'CK3 schema diagnostics are advisory; loading semantics remain unknown.' },
  findings: [{ id: 'overlap', title: 'Trait definition overlap', message: 'Both enabled mods contribute the same trait identity.', category: 'potential_incompatibility', certainty: 'V' }],
} };
function server({ initialScan = false } = {}) {
  const commands: Row[] = [];
  let imported = false;
  let scanned = initialScan;
  const workspace = () => ({ id: 'ck3-workspace', name: 'CK3 stack', game_id: 'ck3', target_platform: 'macos', mode: 'game', revision: imported ? 2 : 1,
    sources: imported ? [{ owner: 'V', path: '/private/ck3/game' }, { owner: 'mod-b', path: '/private/mod-b' }, { owner: 'mod-a', path: '/private/mod-a' }] : [],
    default_playset: imported ? ['mod-b', 'mod-a'] : [],
  });
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { 'Content-Type': 'application/json' } });
    if (path === '/api/bootstrap') return json({ session_token: 'ck3-token', version: '0.1.0', workspaces: [workspace()], fixtures: [], profiles: [{ id: 'eu5-profile', game_id: 'eu5' }, { id: 'ck3-advisory-v1', game_id: 'ck3' }], experiments: [{ id: 'E01', game_id: 'eu5', name: 'EU5 path selection' }], ck3_experiments: [{ id: 'CK3-FILES-01', game_id: 'ck3', name: 'CK3 file selection', status: 'not_run' }], capabilities: {} });
    if (path === '/api/workspaces/ck3-workspace') return json({ workspace: workspace(), scans: scanned ? [{ id: 'ck3-scan' }] : [], candidates: [], releases: [], decisions: [], jobs: [], discoveries: [] });
    if (path === '/api/scans/ck3-scan') return json(ck3Scan);
    if (path === '/api/commands') {
      const body = JSON.parse(String(init?.body)); commands.push(body);
      expect(new Headers(init?.headers).get('X-Session-Token')).toBe('ck3-token');
      if (body.command === 'discover_ck3') return json({ discovery_id: 'discovery-1', discovery: {
        id: 'discovery-1', selected_playset_id: body.payload.playset_id || 'playset-a', complete: false,
        playsets: [{ id: 'playset-a', name: 'Primary', is_active: true }, { id: 'playset-b', name: 'Alternative' }],
        sources: [{ owner: 'V', path: '/private/ck3/game' }, { owner: 'mod-b', path: '/private/mod-b' }, { owner: 'mod-a', path: '/private/mod-a' }],
        playset: ['mod-b', 'mod-a'], diagnostics: [{ code: 'missing_payload', severity: 'warning', message: 'One launcher entry has no available payload.' }],
      } });
      if (body.command === 'import_ck3') { imported = true; return json({ workspace_id: 'ck3-workspace' }); }
      if (body.command === 'scan') { scanned = true; return json({ scan_id: 'ck3-scan' }); }
      return json({ workspace_id: 'ck3-workspace' });
    }
    throw new Error(`Unexpected route ${path}`);
  }));
  return commands;
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('CK3 inspection workflow', () => {
  it('creates a Mac CK3 workspace without requiring source roots before discovery', async () => {
    const commands = server(); const user = userEvent.setup(); render(<App />);
    await screen.findByText('Start with a reproducible snapshot');
    await user.click(screen.getByRole('button', { name: 'New workspace' }));
    const dialog = screen.getByRole('dialog');
    await user.type(within(dialog).getByLabelText('Workspace name'), 'My CK3 playset');
    expect(within(dialog).getByRole('option', { name: 'macOS' })).toBeDisabled();
    await user.selectOptions(within(dialog).getByLabelText('Game'), 'ck3');
    expect(within(dialog).getByRole('option', { name: 'macOS' })).toBeEnabled();
    expect(within(dialog).getByLabelText('Target platform')).toHaveValue('macos');
    expect(within(dialog).getByRole('radio', { name: /Private game inputs/ })).toBeChecked();
    await user.click(within(dialog).getByRole('button', { name: 'Create workspace' }));
    await waitFor(() => expect(commands[0]).toMatchObject({ command: 'create_workspace', payload: { name: 'My CK3 playset', game_id: 'ck3', target_platform: 'macos', mode: 'game' } }));
  });

  it('requires rediscovery after changing a playset and scans the imported enabled order', async () => {
    const commands = server(); const user = userEvent.setup(); render(<App />);
    await screen.findByText('Start with a reproducible snapshot');
    await user.click(screen.getByRole('button', { name: 'Discover CK3 playsets' }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: 'Discover CK3' }));
    await within(dialog).findByText('· One launcher entry has no available payload.');
    expect(within(dialog).getByText('3 available roots · 2 enabled mod entries')).toBeVisible();
    const importButton = within(dialog).getByRole('button', { name: /Import for inspection/ });
    expect(importButton).toBeEnabled();
    await user.selectOptions(within(dialog).getByLabelText('Launcher playset'), 'playset-b');
    expect(importButton).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: 'Rediscover selected playset' }));
    await waitFor(() => expect(importButton).toBeEnabled());
    expect(commands.filter(item => item.command === 'discover_ck3').at(-1)).toMatchObject({ payload: { platform: 'macos', playset_id: 'playset-b' } });
    await user.click(importButton);
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
    await user.click(screen.getByRole('button', { name: 'Scan playset' }));
    const scanDialog = screen.getByRole('dialog');
    expect(within(scanDialog).getByLabelText('Enabled playset order')).toHaveValue('mod-b, mod-a');
    expect(within(scanDialog).queryByRole('tab', { name: 'Contract fixture' })).not.toBeInTheDocument();
    await user.click(within(scanDialog).getByRole('button', { name: 'Capture & scan' }));
    await screen.findByText('Trait definition overlap');
    expect(commands.find(item => item.command === 'import_ck3')).toMatchObject({ payload: { discovery_id: 'discovery-1' } });
    expect(commands.find(item => item.command === 'scan')).toMatchObject({ payload: { playset: ['mod-b', 'mod-a'] }, expected_revision: 2 });
  });

  it('keeps unqualified repair and agent controls disabled without mixing EU5 experiment evidence', async () => {
    const commands = server({ initialScan: true }); const user = userEvent.setup(); render(<App />);
    await screen.findByText('Trait definition overlap');
    await user.click(screen.getByRole('button', { name: /Investigation/ }));
    expect(screen.getAllByRole('button', { name: 'Stage proposal' }).every(button => button.hasAttribute('disabled'))).toBe(true);
    expect(screen.getByRole('button', { name: 'Replay investigation' })).toBeDisabled();
    await user.click(screen.getByRole('button', { name: /Validation & release/ }));
    expect(screen.getByRole('button', { name: 'Validate full playset' })).toBeDisabled();
    expect(screen.getByText('CK3 repair capability is not qualified')).toBeVisible();
    await user.click(screen.getByRole('button', { name: /Rules & evidence/ }));
    await user.click(screen.getByRole('tab', { name: 'Conformance backlog' }));
    expect(screen.queryByText('EU5 path selection')).not.toBeInTheDocument();
    expect(screen.queryByText('E01')).not.toBeInTheDocument();
    expect(screen.getByText('CK3-FILES-01')).toBeVisible();
    expect(screen.getByText('CK3 file selection')).toBeVisible();
    expect(commands.some(item => ['stage', 'investigate', 'runtime_probe'].includes(String(item.command)))).toBe(false);
  });
});
