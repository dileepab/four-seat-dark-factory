// What a handler sees of one HTTP request, and the checks every endpoint shares.

import type { IncomingHttpHeaders } from 'node:http';
import { invalid, unauthenticated } from './errors.ts';
import { instantKey } from './instant.ts';
import { parseObject, type JsonObject } from './json.ts';
import { tokenDigest } from './passwords.ts';
import { store, type User } from './state.ts';

export interface Ctx {
  method: string;
  path: string; // the decoded route path, no query string
  query: URLSearchParams;
  rawQuery: string; // the query string as sent, for the instant parameters (plan 3.2, D79)
  headers: IncomingHttpHeaders;
  params: Record<string, string>; // decoded path parameters
  body: Buffer;
  tooLarge: boolean;
  maxDepth: number; // reset and import allow deeper bodies: an export nests stored request bodies
}

export interface Result {
  status: number;
  body?: unknown; // a JSON body
  raw?: { headers: Record<string, string>; body: Buffer }; // a page or a static file (ui.ts)
}

// The body as one JSON object: 422 when over the size limit, 400 when unreadable.
export function readJson(ctx: Ctx): JsonObject {
  if (ctx.tooLarge) throw invalid('the request body is larger than this endpoint accepts');
  return parseObject(ctx.body, ctx.maxDepth);
}

// `Authorization: Bearer <token>`: scheme case-insensitive, one or more spaces, a token
// without spaces. Anything else, or a token this state did not issue, is 401.
export function authenticate(ctx: Ctx): User {
  const header = ctx.headers.authorization;
  if (typeof header !== 'string') throw unauthenticated();
  const match = /^bearer +(\S+)$/i.exec(header);
  if (!match) throw unauthenticated();
  const st = store.state;
  const userId = st.tokens.get(tokenDigest(match[1]));
  const user = userId === undefined ? undefined : st.users.get(userId);
  if (!user) throw unauthenticated();
  return user;
}

// The first value of a query parameter, percent-decoded only, so a literal '+' stays a plus
// sign (plan 3.2, D79). undefined when absent; null when its percent-encoding is broken.
export function rawParam(ctx: Ctx, name: string): string | null | undefined {
  for (const part of ctx.rawQuery.split('&')) {
    if (part === '') continue;
    const eq = part.indexOf('=');
    let partName: string;
    try {
      partName = decodeURIComponent((eq < 0 ? part : part.slice(0, eq)).replace(/\+/g, ' '));
    } catch {
      continue;
    }
    if (partName !== name) continue;
    try {
      return decodeURIComponent(eq < 0 ? '' : part.slice(eq + 1));
    } catch {
      return null;
    }
  }
  return undefined;
}

// An instant query parameter (plan 3.4): null when absent, 422 when present and not an instant.
export function instantParam(ctx: Ctx, name: string): { text: string; key: string } | null {
  const value = rawParam(ctx, name);
  if (value === undefined) return null;
  const key = value === null ? null : instantKey(value);
  if (key === null) throw invalid(`${name} must be an RFC 3339 instant with an offset`);
  return { text: value as string, key };
}
