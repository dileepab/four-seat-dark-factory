// Idempotent write paths (spec §7, plan 3.9).
//
// A record is keyed by (user, method, canonical path, key) and is stored only when the
// call succeeds, in the same synchronous step as its effects. Everything from the record
// lookup to the commit runs without an await, so concurrent calls that share a record key
// are serialized by the event loop: the first commits, the rest see its record.

import type { Ctx, Result } from './context.ts';
import { ApiError, conflict, invalid } from './errors.ts';
import { cpLength } from './fields.ts';
import { jsonEqual, type JsonObject } from './json.ts';
import { store, type State, type User } from './state.ts';

const MAX_KEY = 255;

// The Idempotency-Key header: absent or empty is 400, longer than 255 characters is 422.
export function idempotencyKey(ctx: Ctx): string {
  const raw = ctx.headers['idempotency-key'];
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value === undefined || value === '') {
    throw new ApiError(400, 'missing_idempotency_key', 'the Idempotency-Key header is required');
  }
  // Node hands header bytes over as latin1; read non-ASCII keys as the UTF-8 they were sent as.
  const key = /[^\x00-\x7f]/.test(value) ? Buffer.from(value, 'latin1').toString('utf8') : value;
  if (cpLength(key) > MAX_KEY) throw invalid(`Idempotency-Key must be at most ${MAX_KEY} characters`);
  return key;
}

export function recordKey(userId: string, method: string, path: string, key: string): string {
  return JSON.stringify([userId, method, path, key]);
}

// Resolve a claimed key first (replay or reuse); otherwise run the operation, which either
// throws without changing anything or commits and returns the response body.
export function idempotent(ctx: Ctx, user: User, key: string, body: JsonObject, run: (st: State) => unknown): Result {
  const st = store.state;
  const id = recordKey(user.id, ctx.method, ctx.path, key);
  const record = st.idem.get(id);
  if (record) {
    if (jsonEqual(record.body, body)) return { status: 200, body: record.response };
    throw conflict('idempotency_key_reuse', 'this Idempotency-Key was already used with a different body');
  }
  const response = run(st);
  st.idem.set(id, { userId: user.id, method: ctx.method, path: ctx.path, key, body, response });
  return { status: 201, body: response };
}
