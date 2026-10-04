// Field rules shared by several endpoints. "Characters" are Unicode code points (D11).

import { invalid, malformed } from './errors.ts';
import { has, type JsonObject } from './json.ts';
import { MAX_AMOUNT, VISIBILITIES, type Visibility } from './state.ts';

export const MAX_NOTE = 200;

export const HANDLE_RE = /^[a-z0-9_]{1,20}$/;

export function cpLength(s: string): number {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

// Exactly one '@', a non-empty local part and domain, no whitespace or control
// characters, at most 254 code points (D12).
export function isEmail(email: string): boolean {
  if (cpLength(email) > 254) return false;
  const at = email.indexOf('@');
  if (at <= 0 || at !== email.lastIndexOf('@') || at === email.length - 1) return false;
  return !/[\s\p{Cc}]/u.test(email);
}

export function emailKey(email: string): string {
  return email.toLowerCase();
}

// Spec §4: the local part, lower-cased, every code point outside [a-z0-9_] replaced
// by '_', truncated to 20 code points.
export function deriveHandle(email: string): string {
  const local = email.slice(0, email.indexOf('@')).toLowerCase();
  let handle = '';
  let n = 0;
  for (const ch of local) {
    handle += /^[a-z0-9_]$/.test(ch) ? ch : '_';
    if (++n === 20) break;
  }
  return handle;
}

// Payment-like fields (plan 3.4). Each returns the valid value or throws 422.

export function requireAmount(body: JsonObject, name = 'amount'): number {
  if (!has(body, name)) throw invalid(`${name} is required`);
  return amountValue(body[name], name);
}

// An integral JSON number from 1 to 1000000000 (1000.0 and 1e3 are integral).
export function amountValue(value: unknown, name = 'amount'): number {
  if (typeof value !== 'number' || !Number.isInteger(value) || value < 1 || value > MAX_AMOUNT) {
    throw invalid(`${name} must be an integer from 1 to ${MAX_AMOUNT}`);
  }
  return value;
}

export function optionalNote(body: JsonObject): string {
  if (!has(body, 'note')) return '';
  const note = body.note;
  if (typeof note !== 'string') throw invalid('note must be a string');
  if (cpLength(note) > MAX_NOTE) throw invalid(`note must be at most ${MAX_NOTE} characters`);
  return note;
}

export function optionalVisibility(body: JsonObject): Visibility {
  if (!has(body, 'visibility')) return 'public';
  const visibility = body.visibility;
  if (typeof visibility !== 'string' || !VISIBILITIES.includes(visibility)) {
    throw invalid('visibility must be "public" or "private"');
  }
  return visibility as Visibility;
}

// A handle field: a string when present (400), present (422).
export function requireHandle(body: JsonObject, name: string): string {
  if (has(body, name) && typeof body[name] !== 'string') throw malformed(`${name} must be a string`);
  if (!has(body, name)) throw invalid(`${name} is required`);
  return body[name] as string;
}

// `limit` and `offset`: plain decimal digits only (spec §5), limit 1 to 200, offset 0 or more.
export function paging(query: URLSearchParams): { limit: number; offset: number } {
  return {
    limit: intParam(query, 'limit', 50, 1, 200),
    offset: intParam(query, 'offset', 0, 0, Number.POSITIVE_INFINITY),
  };
}

function intParam(query: URLSearchParams, name: string, fallback: number, min: number, max: number): number {
  const raw = query.get(name);
  if (raw === null) return fallback;
  if (!/^[0-9]+$/.test(raw)) throw invalid(`${name} must be written as decimal digits`);
  const value = Number(raw);
  if (value < min || value > max) throw invalid(`${name} is out of range`);
  return value;
}
