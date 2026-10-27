// A separate process sets the browser cache before Playwright loads its registry.
import { spawnSync } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontend = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const repo = resolve(frontend, '..');
const [action = 'test', ...args] = process.argv.slice(2);
if (!['install', 'test'].includes(action)) throw new Error('Expected install or test');
const env = { ...process.env, PLAYWRIGHT_BROWSERS_PATH: resolve(repo, '.cache/ms-playwright') };
delete env.OPENROUTER_API_KEY;
delete env.EU5_WORKSPACE;
const result = spawnSync(process.execPath, [resolve(frontend, 'node_modules/@playwright/test/cli.js'), action, ...(action === 'install' ? ['chromium'] : []), ...args], { cwd: frontend, env, stdio: 'inherit' });
if (result.error) throw result.error;
process.exit(result.status ?? 1);
