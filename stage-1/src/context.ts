// What a handler sees of one HTTP request, and the checks every endpoint shares.

import type { IncomingHttpHeaders } from 'node:http';
import { invalid, unauthenticated } from './errors.ts';
import { parseObject, type JsonObject } from './json.ts';
import { tokenDigest } from './passwords.ts';
import { store, type User } from './state.ts';

export interface Ctx {
  method: string;
  path: string; // the decoded route path, no query string
  query: URLSearchParams;
  headers: IncomingHttpHeaders;
  params: Record<string, string>; // decoded path parameters
  body: Buffer;
  tooLarge: boolean;
}

export interface Result {
  status: number;
  body?: unknown;
}

// The body as one JSON object: 422 when over the size limit, 400 when unreadable.
export function readJson(ctx: Ctx): JsonObject {
  if (ctx.tooLarge) throw invalid('the request body is larger than this endpoint accepts');
  return parseObject(ctx.body);
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
