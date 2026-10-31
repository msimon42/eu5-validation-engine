import { cleanup, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Overview from '../screens/Overview';
import type { Scan } from '../types';

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
const workspace = { id: 'ck3-workspace', game_id: 'ck3' as const, mode: 'game', target_platform: 'macos' as const };
const scan: Scan = { id: 'bounded-scan', workspace_id: workspace.id, analysis: {
  files: [{ id: 'file', owner: 'A', path: 'common/traits/example.txt' }],
  definitions: [{ key: 'game/trait/example', state: 'unknown' }],
  findings: [{ id: 'finding', title: 'Loaded schema advisory', category: 'potential_incompatibility' }],
  obligations: [{ id: 'obligation', description: 'Preserve the loaded contribution', owner: 'A', state: 'unknown' }],
  summary: { files: 59088, definitions: 35345, findings: 39597, obligations: 10792, unknown_obligations: 10792, violated_obligations: 0 },
  pagination: { offset: 0, limit: 100, has_more: true, totals: { files: 59088, definitions: 35345, findings: 39597, obligations: 10792 } },
  coverage: { source_inventory_complete: false, unavailable_enabled_sources: ['missing-owner'] },
} };

describe('bounded snapshot overview', () => {
  it('shows complete summary counts and makes loaded-only findings and preservation rows explicit', async () => {
    const user = userEvent.setup();
    render(<Overview scan={scan} workspace={workspace} onScan={vi.fn()} onInvestigate={vi.fn()} busy={false} />);
    expect(within(screen.getByRole('group', { name: 'Source files' })).getByText('59,088')).toBeVisible();
    expect(within(screen.getByRole('group', { name: 'Definitions' })).getByText('35,345')).toBeVisible();
    expect(within(screen.getByRole('group', { name: 'Findings' })).getByText('39,597')).toBeVisible();
    expect(within(screen.getByRole('group', { name: 'Open obligations' })).getByText('10,792')).toBeVisible();
    expect(screen.getByLabelText('Loaded findings')).toHaveTextContent('1 of 39,597 loaded');
    expect(screen.getByLabelText('Loaded preservation obligations')).toHaveTextContent('1 of 10,792 loaded');
    expect(screen.getByText(/1 enabled source was unavailable at capture/)).toBeVisible();
    expect(screen.getByRole('option', { name: 'All loaded categories' })).toBeVisible();
    await user.type(screen.getByRole('textbox', { name: 'Search findings' }), 'not-loaded');
    expect(screen.getByText('No loaded findings match your filter')).toBeVisible();
    expect(screen.getByText(/filters do not search the complete scan/)).toBeVisible();
    expect(within(screen.getByRole('group', { name: 'Findings' })).getByText('39,597')).toBeVisible();
  });

  it('falls back to pagination totals without presenting partial obligation states as a complete count', () => {
    const partial: Scan = { ...scan, analysis: { ...scan.analysis, summary: {}, pagination: {
      totals: { files: 205, definitions: 120, findings: 22, obligations: 9 }, has_more: true,
    } } };
    render(<Overview scan={partial} workspace={workspace} onScan={vi.fn()} onInvestigate={vi.fn()} busy={false} />);
    expect(within(screen.getByRole('group', { name: 'Source files' })).getByText('205')).toBeVisible();
    expect(within(screen.getByRole('group', { name: 'Definitions' })).getByText('120')).toBeVisible();
    expect(within(screen.getByRole('group', { name: 'Findings' })).getByText('22')).toBeVisible();
    expect(within(screen.getByRole('group', { name: 'Open obligations' })).getByText('Unknown or violated · loaded details only')).toBeVisible();
    expect(screen.getByLabelText('Loaded preservation obligations')).toHaveTextContent('1 of 9 loaded');
  });

  it('renders and searches recovered mod labels while retaining duplicate historical finding IDs', async () => {
    const errors = vi.spyOn(console, 'error').mockImplementation(() => {});
    const historical: Scan = { ...scan, analysis: { ...scan.analysis, findings: ['Alpha', 'Beta'].map(name => ({
      id: 'duplicate-historical-id', title: 'CK3 launcher', message: 'directory is absent',
      display_title: `${name} · Mod payload unavailable`, display_target: `mod/${name.toLowerCase()}.mod`,
      display_message: `${name} payload could not be inspected.`, severity: 'error', category: 'uncertain_risk',
    })) } };
    const user = userEvent.setup();
    render(<Overview scan={historical} workspace={workspace} onScan={vi.fn()} onInvestigate={vi.fn()} busy={false} />);
    expect(screen.getByText('Alpha · Mod payload unavailable')).toBeVisible();
    expect(screen.getByText('Beta · Mod payload unavailable')).toBeVisible();
    expect(screen.getByText('Alpha payload could not be inspected.')).toBeVisible();
    await user.type(screen.getByRole('textbox', { name: 'Search findings' }), 'mod/beta.mod');
    expect(screen.queryByText('Alpha · Mod payload unavailable')).not.toBeInTheDocument();
    expect(screen.getByText('Beta · Mod payload unavailable')).toBeVisible();
    expect(errors.mock.calls.flat().join(' ')).not.toMatch(/same key|unique.*key/i);
  });
});
