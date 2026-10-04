// GET /_test/export and POST /_test/import (spec §10, plan 3.12).
//
// The export carries everything the service needs, so an import into any container restores
// the same accounts, password hashes, tokens, money, records, permissions and idempotency
// records, with nothing regenerated or replayed.

import { invalid } from './errors.ts';
import { cpLength, emailKey, HANDLE_RE, isEmail } from './fields.ts';
import { recordKey } from './idempotency.ts';
import { isObject, type JsonObject } from './json.ts';
import { instantKey, tsKey } from './instant.ts';
import {
  addAuthorization, addPayment, addRequest, addUser, AUTHORIZATION_STATUSES, emptyState, formatTs, MAX_AMOUNT,
  MAX_BALANCE, MAX_TTL, REQUEST_STATUSES, sortByTime, VISIBILITIES,
  type AuthorizationStatus, type PasswordHash, type RequestStatus, type State, type Visibility,
} from './state.ts';
import { rfc3339Ms } from './time.ts';

export const TRACK = 'pocketful';
export const FORMAT_VERSION = 1;
// The state layout (D52): 1 is stage 1's (no authorizations), 2 adds the TTL, every
// authorization and each payment's authorization_id. Import reads both.
const SCHEMA = 2;
const TS_RE = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/;
const DIGEST_RE = /^[0-9a-f]{64}$/;
const BASE64_RE = /^[A-Za-z0-9+/]+={0,2}$/;
const MAX_SCRYPT_MEM = 256 * 1024 * 1024; // matches passwords.ts

// One synchronous pass over the live state: later writes cannot change what it returns.
export function exportState(st: State): JsonObject {
  return {
    track: TRACK,
    format_version: FORMAT_VERSION,
    state: {
      schema: SCHEMA,
      currency: st.currency,
      minor_units: st.minorUnits,
      seq: st.seq,
      last_ts: st.lastTs,
      authorization_ttl_seconds: st.authorizationTtl,
      users: [...st.users.values()].map((u) => ({
        id: u.id, email: u.email, password: { ...u.password }, display_name: u.displayName,
        handle: u.handle, balance: u.balance, seq: u.seq,
      })),
      tokens: [...st.tokens].map(([digest, userId]) => ({ digest, user_id: userId })),
      payments: st.payments.map((p) => ({
        id: p.id, from_user_id: p.fromUserId, to_user_id: p.toUserId, amount: p.amount, note: p.note,
        visibility: p.visibility, request_id: p.requestId, settlement_id: p.settlementId,
        authorization_id: p.authorizationId, created_at: p.createdAt, seq: p.seq,
      })),
      requests: st.requests.map((r) => ({
        id: r.id, requester_id: r.requesterId, payer_id: r.payerId, amount: r.amount, note: r.note,
        status: r.status, payment_id: r.paymentId, created_at: r.createdAt, seq: r.seq,
      })),
      splits: [...st.splits.values()].map((s) => ({
        id: s.id, creator_id: s.creatorId, amount: s.amount, note: s.note,
        shares: s.shares.map((share) => ({ handle: share.handle, amount: share.amount })),
        request_ids: [...s.requestIds], created_at: s.createdAt, seq: s.seq,
      })),
      settlements: [...st.settlements.values()].map((s) => ({
        id: s.id, operator_id: s.operatorId, committed_at: s.committedAt, payment_ids: [...s.paymentIds], seq: s.seq,
      })),
      // Stored fields only: `status` as an event set it (an open one past expires_at is
      // expired by the clock, with closed_at null), expires_at exactly as issued or seeded.
      authorizations: st.authorizations.map((a) => ({
        id: a.id, from_user_id: a.fromUserId, to_user_id: a.toUserId, amount: a.amount,
        captured_amount: a.capturedAmount, note: a.note, visibility: a.visibility, status: a.status,
        expires_at: a.expiresAt, payment_id: a.paymentId, payment_ids: [...a.paymentIds],
        created_at: a.createdAt, closed_at: a.closedAt, seq: a.seq,
      })),
      operator_ids: [...st.operators],
      idempotency: [...st.idem.values()].map((r) => ({
        user_id: r.userId, method: r.method, path: r.path, key: r.key, body: r.body, response: r.response,
      })),
    },
  };
}

function check(condition: boolean, message: string): void {
  if (!condition) throw invalid(`invalid export: ${message}`);
}

function isInt(v: unknown, min: number, max: number): v is number {
  return typeof v === 'number' && Number.isInteger(v) && v >= min && v <= max;
}

function isId(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0 && cpLength(v) <= 64;
}

function isTs(v: unknown): v is string {
  return typeof v === 'string' && TS_RE.test(v) && !Number.isNaN(Date.parse(v));
}

// A record time: issued by the service, or seeded in any instant form (plan 3.4, 3.10).
function isInstant(v: unknown): v is string {
  return instantKey(v) !== null;
}

function isRef(v: unknown): v is string | null {
  return v === null || typeof v === 'string';
}

function list(state: JsonObject, key: string): JsonObject[] {
  const v = state[key];
  check(Array.isArray(v), `${key} must be an array`);
  (v as unknown[]).forEach((item, i) => check(isObject(item), `${key}[${i}] must be an object`));
  return v as JsonObject[];
}

function passwordRecord(v: unknown, what: string): PasswordHash {
  check(isObject(v), `${what} must be an object`);
  const o = v as JsonObject;
  const ok = o.alg === 'scrypt'
    && isInt(o.N, 2, 2 ** 20) && ((o.N as number) & ((o.N as number) - 1)) === 0
    && isInt(o.r, 1, 32) && isInt(o.p, 1, 16)
    && 128 * (o.N as number) * (o.r as number) * (o.p as number) <= MAX_SCRYPT_MEM
    && typeof o.salt === 'string' && BASE64_RE.test(o.salt)
    && typeof o.hash === 'string' && BASE64_RE.test(o.hash) && Buffer.from(o.hash, 'base64').length === 32;
  check(ok, `${what} must be a scrypt hash record`);
  return { alg: 'scrypt', N: o.N as number, r: o.r as number, p: o.p as number, salt: o.salt as string, hash: o.hash as string };
}

// Validate the whole export and build the state it describes. Throws 422 before anything
// changes; the caller swaps the result in.
export function importState(body: JsonObject): State {
  check(body.track === TRACK, `track must be "${TRACK}"`);
  check(body.format_version === FORMAT_VERSION, `format_version must be ${FORMAT_VERSION}`);
  check(isObject(body.state), 'state must be an object');
  const s = body.state as JsonObject;
  check(s.schema === 1 || s.schema === SCHEMA, `state.schema must be 1 or ${SCHEMA}`);
  const v2 = s.schema === SCHEMA;
  check(typeof s.currency === 'string' && /^[A-Z]{3}$/.test(s.currency), 'currency must be three capital letters');
  check(isInt(s.minor_units, 0, 3) && s.minor_units !== 1, 'minor_units must be 0, 2 or 3');
  check(isInt(s.seq, 0, Number.MAX_SAFE_INTEGER), 'seq must be a non-negative integer');
  check(isTs(s.last_ts), 'last_ts must be a timestamp');

  // A schema-1 state (an unchanged stage-1 export) has the default TTL and no authorizations.
  if (v2) {
    check(isInt(s.authorization_ttl_seconds, 1, MAX_TTL), `authorization_ttl_seconds must be an integer from 1 to ${MAX_TTL}`);
  }

  const st = emptyState();
  st.currency = s.currency as string;
  st.minorUnits = s.minor_units as number;
  if (v2) st.authorizationTtl = s.authorization_ttl_seconds as number;
  let seq = s.seq as number;
  let lastTs = s.last_ts as string;
  // The clock starts at the latest time in the state, in the service's own form (rounded up to
  // the millisecond when a seeded time carries more digits).
  const see = (entitySeq: unknown, ts: string | null, what: string) => {
    check(isInt(entitySeq, 0, Number.MAX_SAFE_INTEGER), `${what}.seq must be a non-negative integer`);
    seq = Math.max(seq, entitySeq as number);
    if (ts !== null && tsKey(ts) > tsKey(lastTs)) lastTs = formatTs(rfc3339Ms(ts) as number);
  };

  list(s, 'users').forEach((u, i) => {
    const what = `users[${i}]`;
    check(isId(u.id) && !st.users.has(u.id), `${what}.id must be a unique id`);
    check(typeof u.email === 'string' && isEmail(u.email) && !st.usersByEmail.has(emailKey(u.email)), `${what}.email must be a unique email`);
    check(typeof u.display_name === 'string', `${what}.display_name must be a string`);
    check(typeof u.handle === 'string' && HANDLE_RE.test(u.handle) && !st.usersByHandle.has(u.handle), `${what}.handle must be a unique handle`);
    check(isInt(u.balance, 0, MAX_BALANCE), `${what}.balance must be an integer from 0 to 2^53`);
    see(u.seq, null, what);
    addUser(st, {
      id: u.id as string, email: u.email as string, emailKey: emailKey(u.email as string),
      password: passwordRecord(u.password, `${what}.password`), displayName: u.display_name as string,
      handle: u.handle as string, balance: u.balance as number, opening: 0, seq: u.seq as number,
    });
  });

  list(s, 'tokens').forEach((t, i) => {
    check(typeof t.digest === 'string' && DIGEST_RE.test(t.digest) && !st.tokens.has(t.digest), `tokens[${i}].digest must be a unique SHA-256 hex digest`);
    check(typeof t.user_id === 'string' && st.users.has(t.user_id), `tokens[${i}].user_id must name a user`);
    st.tokens.set(t.digest as string, t.user_id as string);
  });

  list(s, 'payments').forEach((p, i) => {
    const what = `payments[${i}]`;
    check(isId(p.id) && !st.paymentsById.has(p.id), `${what}.id must be a unique id`);
    check(typeof p.from_user_id === 'string' && st.users.has(p.from_user_id), `${what}.from_user_id must name a user`);
    check(typeof p.to_user_id === 'string' && st.users.has(p.to_user_id) && p.to_user_id !== p.from_user_id, `${what}.to_user_id must name another user`);
    check(isInt(p.amount, 0, MAX_AMOUNT), `${what}.amount must be an integer from 0 to ${MAX_AMOUNT}`);
    check(typeof p.note === 'string', `${what}.note must be a string`);
    check(typeof p.visibility === 'string' && VISIBILITIES.includes(p.visibility), `${what}.visibility must be public or private`);
    check(isRef(p.request_id) && isRef(p.settlement_id) && (!v2 || isRef(p.authorization_id)),
      `${what} links must be strings or null`);
    check(isInstant(p.created_at), `${what}.created_at must be an instant`);
    see(p.seq, p.created_at as string, what);
    addPayment(st, {
      id: p.id as string, fromUserId: p.from_user_id as string, toUserId: p.to_user_id as string,
      amount: p.amount as number, note: p.note as string, visibility: p.visibility as Visibility,
      requestId: p.request_id as string | null, settlementId: p.settlement_id as string | null,
      authorizationId: v2 ? p.authorization_id as string | null : null,
      createdAt: p.created_at as string, seq: p.seq as number,
    });
  });

  list(s, 'requests').forEach((r, i) => {
    const what = `requests[${i}]`;
    check(isId(r.id) && !st.requestsById.has(r.id), `${what}.id must be a unique id`);
    check(typeof r.requester_id === 'string' && st.users.has(r.requester_id), `${what}.requester_id must name a user`);
    check(typeof r.payer_id === 'string' && st.users.has(r.payer_id) && r.payer_id !== r.requester_id, `${what}.payer_id must name another user`);
    check(isInt(r.amount, 0, MAX_AMOUNT), `${what}.amount must be an integer from 0 to ${MAX_AMOUNT}`);
    check(typeof r.note === 'string', `${what}.note must be a string`);
    check(typeof r.status === 'string' && REQUEST_STATUSES.includes(r.status), `${what}.status must be a request status`);
    check(isRef(r.payment_id), `${what}.payment_id must be a string or null`);
    check(isTs(r.created_at), `${what}.created_at must be a timestamp`);
    see(r.seq, r.created_at as string, what);
    addRequest(st, {
      id: r.id as string, requesterId: r.requester_id as string, payerId: r.payer_id as string,
      amount: r.amount as number, note: r.note as string, status: r.status as RequestStatus,
      paymentId: r.payment_id as string | null, createdAt: r.created_at as string, seq: r.seq as number,
    });
  });

  list(s, 'splits').forEach((sp, i) => {
    const what = `splits[${i}]`;
    check(isId(sp.id) && !st.splits.has(sp.id), `${what}.id must be a unique id`);
    check(typeof sp.creator_id === 'string' && st.users.has(sp.creator_id), `${what}.creator_id must name a user`);
    check(isInt(sp.amount, 1, MAX_AMOUNT), `${what}.amount must be an integer from 1 to ${MAX_AMOUNT}`);
    check(typeof sp.note === 'string', `${what}.note must be a string`);
    check(Array.isArray(sp.shares) && (sp.shares as unknown[]).every((sh) => isObject(sh)
      && typeof sh.handle === 'string' && isInt(sh.amount, 0, MAX_AMOUNT)), `${what}.shares must be handle and amount pairs`);
    check(Array.isArray(sp.request_ids) && (sp.request_ids as unknown[]).every((id) => typeof id === 'string' && st.requestsById.has(id)),
      `${what}.request_ids must name requests`);
    check(isTs(sp.created_at), `${what}.created_at must be a timestamp`);
    see(sp.seq, sp.created_at as string, what);
    st.splits.set(sp.id as string, {
      id: sp.id as string, creatorId: sp.creator_id as string, amount: sp.amount as number, note: sp.note as string,
      shares: (sp.shares as JsonObject[]).map((sh) => ({ handle: sh.handle as string, amount: sh.amount as number })),
      requestIds: [...(sp.request_ids as string[])], createdAt: sp.created_at as string, seq: sp.seq as number,
    });
  });

  list(s, 'settlements').forEach((se, i) => {
    const what = `settlements[${i}]`;
    check(isId(se.id) && !st.settlements.has(se.id), `${what}.id must be a unique id`);
    check(typeof se.operator_id === 'string' && st.users.has(se.operator_id), `${what}.operator_id must name a user`);
    check(isTs(se.committed_at), `${what}.committed_at must be a timestamp`);
    check(Array.isArray(se.payment_ids) && (se.payment_ids as unknown[]).every((id) => typeof id === 'string' && st.paymentsById.has(id)),
      `${what}.payment_ids must name payments`);
    see(se.seq, se.committed_at as string, what);
    st.settlements.set(se.id as string, {
      id: se.id as string, operatorId: se.operator_id as string, committedAt: se.committed_at as string,
      paymentIds: [...(se.payment_ids as string[])], seq: se.seq as number,
    });
  });

  // Display-only links (payment_id, payment_ids, a payment's authorization_id) are checked by
  // type only, as reset checks them (D62).
  if (v2) {
    list(s, 'authorizations').forEach((a, i) => {
      const what = `authorizations[${i}]`;
      check(isId(a.id) && !st.authorizationsById.has(a.id), `${what}.id must be a unique id`);
      check(typeof a.from_user_id === 'string' && st.users.has(a.from_user_id), `${what}.from_user_id must name a user`);
      check(typeof a.to_user_id === 'string' && st.users.has(a.to_user_id) && a.to_user_id !== a.from_user_id,
        `${what}.to_user_id must name another user`);
      check(isInt(a.amount, 0, MAX_AMOUNT), `${what}.amount must be an integer from 0 to ${MAX_AMOUNT}`);
      check(isInt(a.captured_amount, 0, a.amount as number), `${what}.captured_amount must be an integer from 0 to amount`);
      check(typeof a.note === 'string', `${what}.note must be a string`);
      check(typeof a.visibility === 'string' && VISIBILITIES.includes(a.visibility), `${what}.visibility must be public or private`);
      check(typeof a.status === 'string' && AUTHORIZATION_STATUSES.includes(a.status), `${what}.status must be an authorization status`);
      check(a.status !== 'open' || (a.captured_amount as number) < (a.amount as number), `${what} is open with nothing left to capture`);
      const expiresMs = typeof a.expires_at === 'string' && a.expires_at.length <= 64 ? rfc3339Ms(a.expires_at) : null;
      check(expiresMs !== null, `${what}.expires_at must be an RFC 3339 date-time`);
      check(isRef(a.payment_id), `${what}.payment_id must be a string or null`);
      check(Array.isArray(a.payment_ids) && (a.payment_ids as unknown[]).every((id) => typeof id === 'string'),
        `${what}.payment_ids must be an array of strings`);
      check(isInstant(a.created_at), `${what}.created_at must be an instant`);
      check(a.closed_at === null || isTs(a.closed_at), `${what}.closed_at must be a timestamp or null`);
      see(a.seq, a.created_at as string, what);
      if (a.closed_at !== null) see(a.seq, a.closed_at as string, what);
      addAuthorization(st, {
        id: a.id as string, fromUserId: a.from_user_id as string, toUserId: a.to_user_id as string,
        amount: a.amount as number, capturedAmount: a.captured_amount as number, note: a.note as string,
        visibility: a.visibility as Visibility, status: a.status as AuthorizationStatus,
        expiresAt: a.expires_at as string, expiresMs: expiresMs as number,
        paymentId: a.payment_id as string | null, paymentIds: [...(a.payment_ids as string[])],
        createdAt: a.created_at as string, closedAt: a.closed_at as string | null,
        seededClosed: false, baseCaptured: 0, seq: a.seq as number,
      });
    });
  }

  const operators = s.operator_ids;
  check(Array.isArray(operators) && (operators as unknown[]).every((id) => typeof id === 'string' && st.users.has(id)),
    'operator_ids must name users');
  for (const id of operators as string[]) st.operators.add(id);

  list(s, 'idempotency').forEach((r, i) => {
    const what = `idempotency[${i}]`;
    check(typeof r.user_id === 'string' && st.users.has(r.user_id), `${what}.user_id must name a user`);
    check(typeof r.method === 'string' && typeof r.path === 'string', `${what} needs a method and a path`);
    check(typeof r.key === 'string' && r.key.length > 0 && cpLength(r.key) <= 255, `${what}.key must be 1 to 255 characters`);
    check(isObject(r.body) && r.response !== undefined, `${what} needs the request body and the response`);
    const id = recordKey(r.user_id as string, r.method as string, r.path as string, r.key as string);
    check(!st.idem.has(id), `${what} repeats a record`);
    st.idem.set(id, {
      userId: r.user_id as string, method: r.method as string, path: r.path as string,
      key: r.key as string, body: r.body, response: r.response,
    });
  });

  st.seq = seq;
  st.lastTs = lastTs;
  // Opening balances (plan 3.7, D69): the imported balance minus the net of all the user's
  // payments. A captured amount not matched by linked capture payments counts from creation.
  for (const user of st.users.values()) {
    let net = 0;
    for (const p of st.paymentsOf.get(user.id) ?? []) net += p.fromUserId === user.id ? -p.amount : p.amount;
    user.opening = user.balance - net;
  }
  for (const a of st.authorizations) {
    const linked = (st.capturesOf.get(a.id) ?? []).reduce((sum, p) => sum + p.amount, 0);
    a.baseCaptured = Math.max(0, a.capturedAmount - linked);
  }
  sortByTime(st);

  // The holds still open at the import's time (its clock: never before the imported
  // timestamps) must fit within each payer's total. One past its deadline holds nothing: its
  // payer may have spent that money before the export.
  const importMs = Math.max(Date.now(), Date.parse(lastTs));
  const held = new Map<string, number>();
  for (const a of st.authorizations) {
    if (a.status === 'open' && a.expiresMs > importMs) {
      held.set(a.fromUserId, (held.get(a.fromUserId) ?? 0) + a.amount - a.capturedAmount);
    }
  }
  for (const [userId, amount] of held) {
    check(amount <= st.users.get(userId)!.balance, `the open authorizations of ${userId} hold more than its total`);
  }
  return st;
}
