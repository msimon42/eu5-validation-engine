import type { CommandKind } from './generated/contracts';
export type Row = Record<string, unknown>;
export interface Workspace extends Row { id: string; name?: string; mode?: string; revision?: number; game_id?: 'eu5' | 'ck3'; target_platform?: 'windows' | 'macos' }
export interface Bootstrap extends Row {
  session_token: string; version: string; workspaces: Workspace[];
  fixtures: (Row | string)[]; profiles: (Row | string)[]; experiments: (Row | string)[];
  ck3_experiments?: (Row | string)[];
  capabilities: Row;
  inference?: Row;
}
export interface WorkspaceDetail extends Row {
  workspace: Workspace; scans: Row[]; candidates: Row[]; releases: Row[]; jobs: Row[]; decisions: Row[];
}
export interface Analysis extends Row {
  summary?: Row; files?: Row[] | Record<string, Row>; definitions?: Row[] | Record<string, Row>;
  findings?: Row[]; obligations?: Row[]; coverage?: Row; graphs?: Row; profile?: Row | string;
}
export interface Scan extends Row { id: string; workspace_id: string; analysis: Analysis; inputs?: Row[]; playset?: string[]; created_at?: string }
export interface Candidate extends Row {
  id: string; status: string; plan: Row; validation?: Row; scan_id?: string;
}
export interface Job extends Row { id: string; state: string; phase?: string; progress?: Row; result?: Row; error?: Row | string }
export interface CommandResult extends Row { job_id?: string; scan_id?: string; candidate_id?: string; workspace_id?: string; artifact_id?: string }
export type Command = CommandKind;
export type Screen = 'overview' | 'investigation' | 'decisions' | 'validation' | 'evidence';

export function rows(value: unknown): Row[] {
  if (Array.isArray(value)) return value.map((item, index) => typeof item === 'object' && item !== null ? item as Row : { id: String(index), value: item });
  if (value && typeof value === 'object') return Object.entries(value).map(([id, item]) => item && typeof item === 'object' ? { id, ...item as Row } : { id, value: item });
  return [];
}
export function text(value: unknown, fallback = '—'): string {
  if (value === undefined || value === null || value === '') return fallback;
  if (typeof value === 'object') return JSON.stringify(value, null, 2);
  return String(value);
}
export function label(value: unknown, fallback = 'Unknown'): string {
  return text(value, fallback).replaceAll('_', ' ').replace(/\b\w/g, char => char.toUpperCase());
}
export function object(value: unknown): Row { return value && typeof value === 'object' && !Array.isArray(value) ? value as Row : {}; }
export function idOf(value: Row): string { return text(value.id ?? value.scan_id ?? value.candidate_id, ''); }
export function gameName(value: Row | undefined): string { return value?.game_id === 'ck3' ? 'Crusader Kings III' : 'Europa Universalis V'; }
