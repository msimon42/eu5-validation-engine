import { test as base, expect, type Page, type Response } from '@playwright/test';
import { spawn, execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const python = process.env.EU5_E2E_PYTHON || path.join(repo, '.venv', process.platform === 'win32' ? 'Scripts/python.exe' : 'bin/python');

export interface DiskFixture {
  id: string;
  fixture_path: string;
  manifest_hash: string;
  sources: Array<{ owner: string; path: string; manifest: Array<{ path: string; sha256: string; size: number }> }>;
}

export interface App {
  url: string;
  root: string;
  state: string;
  fixture(id: string): DiskFixture;
  inspectZip(filename: string): { names: string[]; manifest: Record<string, any>; files: Record<string, { bytes_base64: string; sha256: string }> };
}

function filePaths(root: string): string[] {
  const result: string[] = [];
  if (!fs.existsSync(root)) return result;
  function walk(directory: string) {
    for (const entry of fs.readdirSync(directory).sort()) {
      const filename = path.join(directory, entry);
      const info = fs.lstatSync(filename);
      if (info.isSymbolicLink()) throw new Error('Test source unexpectedly contains a link');
      if (info.isDirectory()) walk(filename);
      else if (info.isFile()) result.push(path.relative(root, filename).split(path.sep).join('/'));
      else throw new Error('Test tree unexpectedly contains a nonregular file');
    }
  }
  walk(root);
  return result;
}

export function hashTree(root: string): Record<string, string> {
  return Object.fromEntries(filePaths(root).map(relative => [relative,
    createHash('sha256').update(fs.readFileSync(path.join(root, relative))).digest('hex')]));
}

export function expectInactive(app: App) {
  // Only names matter here. The live coordinator lock cannot be read on Windows.
  const names = filePaths(app.state);
  expect(names.filter(name => /(^|\/)(active-release\.json|playsets\.json|content_load\.json)$/.test(name))).toEqual([]);
}

export const test = base.extend<{ app: App }>({
  app: async ({ page }, use, testInfo) => {
    if (!fs.existsSync(python)) throw new Error('Python environment missing. Run uv sync --frozen, or use uv run python scripts/test_e2e.py.');
    const root = fs.mkdtempSync(path.join(fs.realpathSync(os.tmpdir()), 'eu5-browser-e2e-'));
    const state = path.join(root, 'state');
    const ready = path.join(root, 'ready.json');
    const env: NodeJS.ProcessEnv = { ...process.env, PYTHONUNBUFFERED: '1' };
    delete env.OPENROUTER_API_KEY;
    delete env.EU5_WORKSPACE;
    const child = spawn(python, [path.join(repo, 'frontend/e2e/server.py'), '--state', state, '--ready', ready], { cwd: repo, env, stdio: ['ignore', 'pipe', 'pipe'] });
    const closed = new Promise<void>(resolve => child.once('close', () => resolve()));
    let log = '';
    child.stdout?.on('data', chunk => { log = (log + chunk.toString()).slice(-100_000); });
    child.stderr?.on('data', chunk => { log = (log + chunk.toString()).slice(-100_000); });
    let launchError: Error | undefined;
    child.on('error', error => { launchError = error; });
    const forbidden: string[] = [];
    const browserErrors: string[] = [];
    page.on('pageerror', error => browserErrors.push(error.message));
    try {
      await expect.poll(() => {
        if (launchError) throw launchError;
        if (child.exitCode !== null) throw new Error(`Real server exited during startup: ${log}`);
        return fs.existsSync(ready);
      }, { timeout: 20_000, message: 'Real Python server publishes its bound port' }).toBe(true);
      const { url } = JSON.parse(fs.readFileSync(ready, 'utf8')) as { url: string };
      await expect.poll(async () => {
        try { return (await page.request.get(`${url}/api/health`, { timeout: 1000 })).status(); }
        catch { return 0; }
      }, { timeout: 20_000, message: 'Real FastAPI startup completes' }).toBe(200);
      // Network isolation only: all local app requests pass through unmodified.
      await page.context().route('**/*', async route => {
        const target = new URL(route.request().url());
        if (target.origin === url || ['data:', 'blob:', 'about:'].includes(target.protocol)) return route.continue();
        forbidden.push(target.origin);
        return route.abort('blockedbyclient');
      });
      const helper = (action: string, filename: string, identifier?: string) => JSON.parse(execFileSync(python,
        [path.join(repo, 'frontend/e2e/fixture_tool.py'), action, filename, ...(identifier ? ['--fixture', identifier] : [])],
        { cwd: repo, env, encoding: 'utf8' }));
      const app: App = {
        url, root, state,
        fixture: id => helper('materialize', path.join(root, `Synthetic mods ${id} – offline`), id),
        inspectZip: filename => helper('inspect_zip', filename),
      };
      await use(app);
      expect(forbidden, 'No external requests are permitted in the offline browser suite').toEqual([]);
      expect(browserErrors, 'No unhandled browser application errors').toEqual([]);
    } finally {
      try {
        if (!launchError && child.exitCode === null && child.signalCode === null) child.kill(process.platform === 'win32' ? 'SIGTERM' : 'SIGINT');
        const force = setTimeout(() => { child.kill('SIGKILL'); }, 5000);
        let limit: ReturnType<typeof setTimeout> | undefined;
        try {
          await Promise.race([closed, new Promise<never>((_, reject) => {
            limit = setTimeout(() => reject(new Error('The isolated backend did not stop within 10 seconds')), 10_000);
          })]);
        } finally { clearTimeout(force); clearTimeout(limit); }
      } finally {
        try { await testInfo.attach('backend.log', { body: log || 'Server produced no errors.', contentType: 'text/plain' }); }
        finally { fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }); }
      }
    }
  },
});

export async function commandResult(page: Page, action: string, trigger: () => Promise<unknown>) {
  const response = page.waitForResponse(response => {
    if (!response.url().endsWith('/api/commands') || response.request().method() !== 'POST') return false;
    return response.request().postDataJSON().command === action;
  });
  await trigger();
  const received: Response = await response;
  expect(received.status(), await received.text()).toBe(202);
  const submitted = received.request().postDataJSON();
  let result = await received.json();
  if (result.job_id) {
    let job: Record<string, any> = {};
    await expect.poll(async () => {
      const jobResponse = await page.request.get(new URL(`/api/jobs/${result.job_id}`, received.url()).href);
      job = await jobResponse.json();
      return ['completed', 'failed', 'cancelled'].includes(job.state);
    }, { timeout: 20_000, message: `${action} reaches a recorded terminal job state` }).toBe(true);
    result = { ...result, ...job.result, job };
  }
  return { result, submitted };
}

export async function importAndScan(page: Page, app: App, fixture: DiskFixture) {
  await page.goto(app.url);
  await page.getByRole('button', { name: 'New workspace', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('Workspace name', { exact: true }).fill(`On-disk ${fixture.id}`);
  await dialog.getByRole('textbox', { name: /^Synthetic fixture folder \(optional\)/ }).fill(fixture.fixture_path);
  const created = await commandResult(page, 'create_workspace', () => dialog.getByRole('button', { name: 'Create workspace', exact: true }).click());
  const workspaceId = created.result.workspace_id as string;
  await expect(page.getByRole('combobox', { name: 'Current workspace' })).toHaveValue(workspaceId);
  const workspace = await (await page.request.get(`${app.url}/api/workspaces/${workspaceId}`)).json();
  expect(workspace.workspace.mode).toBe('synthetic');
  expect(workspace.workspace.fixture_path).toBe(fixture.fixture_path);
  expect(workspace.workspace.sources.map((source: { path: string }) => fs.realpathSync(source.path)).sort()).toEqual(fixture.sources.map(source => fs.realpathSync(source.path)).sort());
  await page.getByRole('button', { name: 'Scan playset', exact: true }).click();
  await expect(page.getByRole('dialog').getByLabel('Synthetic fixture folder', { exact: true })).toHaveValue(fixture.fixture_path);
  const scanned = await commandResult(page, 'scan', () => page.getByRole('button', { name: 'Capture & scan', exact: true }).click());
  expect(scanned.submitted.payload).toEqual({}); // No fixture_id or base64 inputs bypass disk scanning.
  expect(scanned.result.job.state, JSON.stringify(scanned.result.job)).toBe('completed');
  await expect(page.getByText('Immutable scan captured.', { exact: false })).toBeVisible();
  const scan = await (await page.request.get(`${app.url}/api/scans/${scanned.result.scan_id}`)).json();
  expect(scan.profile.kind).toBe('synthetic');
  expect(scan.fixture_manifest_hash).toBe(fixture.manifest_hash);
  expect(scan.source_roots.map((source: { path: string }) => fs.realpathSync(source.path)).sort()).toEqual(fixture.sources.map(source => fs.realpathSync(source.path)).sort());
  return { workspaceId, scan };
}

export async function stage(page: Page) {
  await page.getByRole('button', { name: 'Investigation', exact: true }).click();
  const staged = await commandResult(page, 'stage', () => page.getByRole('button', { name: 'Stage proposal', exact: true }).first().click());
  expect(staged.result.job.state, JSON.stringify(staged.result.job)).toBe('completed');
  await expect(page.getByText('Candidate created in managed staging.', { exact: false })).toBeVisible();
  return staged.result;
}

export async function validate(page: Page) {
  await page.getByRole('button', { name: 'Validation & release', exact: true }).click();
  const validated = await commandResult(page, 'validate', () => page.getByRole('button', { name: 'Validate full playset', exact: true }).click());
  expect(validated.result.job.state, JSON.stringify(validated.result.job)).toBe('completed');
  await expect(page.getByText('Validation results recorded.', { exact: false })).toBeVisible();
  return validated.result;
}

export { expect };
