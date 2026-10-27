import type { Bootstrap, Command, CommandResult, Row } from './types';

export class ApiError extends Error {
  constructor(message: string, public status: number, public detail: unknown) { super(message); this.name = 'ApiError'; }
}
let sessionToken = '';
export function setSessionToken(token: string) { sessionToken = token; }

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.method && options.method !== 'GET') {
    headers.set('Content-Type', 'application/json');
    headers.set('X-Session-Token', sessionToken);
  }
  let response: Response;
  try { response = await fetch(path, { ...options, headers, credentials: 'same-origin' }); }
  catch { throw new ApiError('The local service is unavailable. Start the backend, then reconnect.', 0, null); }
  const data: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = data && typeof data === 'object' ? (data as Row).detail ?? data : data;
    const message = typeof detail === 'string' ? detail : detail && typeof detail === 'object' ? String((detail as Row).message ?? (detail as Row).reason ?? JSON.stringify(detail)) : `Request failed (${response.status}).`;
    throw new ApiError(message, response.status, detail);
  }
  return data as T;
}
export async function bootstrap(): Promise<Bootstrap> {
  const data = await request<Bootstrap>('/api/bootstrap');
  setSessionToken(data.session_token);
  return data;
}
export function command(command: Command, workspaceId: string | undefined, payload: Row, revision?: number): Promise<CommandResult> {
  return request('/api/commands', { method: 'POST', body: JSON.stringify({ command, workspace_id: workspaceId, payload, idempotency_key: crypto.randomUUID(), expected_revision: revision }) });
}
