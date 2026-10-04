// POST /_test/reset: validate a fixture completely, then build the new state aside (plan 3.11).

import { invalid } from './errors.ts';
import { cpLength, emailKey, HANDLE_RE, isEmail } from './fields.ts';
import { has, isObject, type JsonObject } from './json.ts';
import { hashPassword, SEED_COST } from './passwords.ts';
import {
  addAuthorization, addPayment, addRequest, addUser, AUTHORIZATION_STATUSES, DEFAULT_TTL, emptyState, formatTs,
  MAX_AMOUNT, MAX_BALANCE, MAX_TTL, nextSeq, REQUEST_STATUSES, VISIBILITIES,
  type AuthorizationStatus, type RequestStatus, type State, type Visibility,
} from './state.ts';
import { rfc3339Ms } from './time.ts';

const MAX_USERS = 1000;

interface SeedUser {
  id: string;
  email: string;
  password: string;
  displayName: string;
  handle: string;
  balance: number;
}

interface SeedPayment {
  id: string;
  fromUserId: string;
  toUserId: string;
  amount: number;
  note: string;
  visibility: Visibility;
  requestId: string | null;
  settlementId: string | null;
  authorizationId: string | null;
}

interface SeedRequest {
  id: string;
  requesterId: string;
  payerId: string;
  amount: number;
  note: string;
  status: RequestStatus;
  paymentId: string | null;
}

interface SeedAuthorization {
  id: string;
  fromUserId: string;
  toUserId: string;
  amount: number;
  capturedAmount: number;
  note: string;
  visibility: Visibility;
  status: AuthorizationStatus;
  expiresAt: string;
  expiresMs: number;
  paymentId: string | null;
  paymentIds: string[];
}

interface Fixture {
  currency: string;
  minorUnits: number;
  ttl: number;
  users: SeedUser[];
  payments: SeedPayment[];
  requests: SeedRequest[];
  authorizations: SeedAuthorization[];
  operators: string[];
}

function check(condition: boolean, message: string): void {
  if (!condition) throw invalid(`invalid fixture: ${message}`);
}

function isInt(v: unknown): v is number {
  return typeof v === 'number' && Number.isInteger(v);
}

function isId(v: unknown): v is string {
  return typeof v === 'string' && v.length > 0 && cpLength(v) <= 64;
}

// An optional collection: absent or null is empty; anything else must be an array.
function optionalArray(body: JsonObject, key: string): unknown[] {
  const v = body[key];
  if (v === undefined || v === null) return [];
  check(Array.isArray(v), `${key} must be an array`);
  return v as unknown[];
}

function optionalString(v: unknown, what: string): string {
  if (v === undefined || v === null) return '';
  check(typeof v === 'string', `${what} must be a string`);
  return v as string;
}

function optionalRef(v: unknown, what: string): string | null {
  if (v === undefined || v === null) return null;
  check(typeof v === 'string', `${what} must be a string or null`);
  return v as string;
}

function absent(v: unknown): boolean {
  return v === undefined || v === null;
}

// Validate everything against the reset's own time `resetMs` (the seeded holds that count are
// the ones still open then). Nothing here touches the live state.
export function validateFixture(body: JsonObject, resetMs: number): Fixture {
  check(typeof body.currency === 'string' && /^[A-Z]{3}$/.test(body.currency), 'currency must be three capital letters');
  check(isInt(body.minor_units) && [0, 2, 3].includes(body.minor_units), 'minor_units must be 0, 2 or 3');

  check(Array.isArray(body.users), 'users must be an array');
  const rawUsers = body.users as unknown[];
  check(rawUsers.length <= MAX_USERS, `at most ${MAX_USERS} users`);
  const ids = new Set<string>();
  const emails = new Set<string>();
  const handles = new Set<string>();
  const users: SeedUser[] = rawUsers.map((u, i) => {
    check(isObject(u), `users[${i}] must be an object`);
    const o = u as JsonObject;
    check(isId(o.id) && !ids.has(o.id), `users[${i}].id must be a unique string of 1 to 64 characters`);
    check(typeof o.email === 'string' && isEmail(o.email) && !emails.has(emailKey(o.email)),
      `users[${i}].email must be a unique local@domain address`);
    check(typeof o.password === 'string' && o.password.length > 0, `users[${i}].password must be a non-empty string`);
    check(typeof o.display_name === 'string', `users[${i}].display_name must be a string`);
    check(typeof o.handle === 'string' && HANDLE_RE.test(o.handle) && !handles.has(o.handle),
      `users[${i}].handle must be unique and match ^[a-z0-9_]{1,20}$`);
    check(isInt(o.balance) && o.balance >= 0 && o.balance <= MAX_BALANCE,
      `users[${i}].balance must be an integer from 0 to 2^53`);
    const user: SeedUser = {
      id: o.id as string, email: o.email as string, password: o.password as string,
      displayName: o.display_name as string, handle: o.handle as string, balance: o.balance as number,
    };
    ids.add(user.id);
    emails.add(emailKey(user.email));
    handles.add(user.handle);
    return user;
  });

  const paymentIds = new Set<string>();
  const payments: SeedPayment[] = optionalArray(body, 'payments').map((p, i) => {
    const what = `payments[${i}]`;
    check(isObject(p), `${what} must be an object`);
    const o = p as JsonObject;
    check(isId(o.id) && !paymentIds.has(o.id), `${what}.id must be a unique string of 1 to 64 characters`);
    check(typeof o.from_user_id === 'string' && ids.has(o.from_user_id), `${what}.from_user_id must name a user`);
    check(typeof o.to_user_id === 'string' && ids.has(o.to_user_id), `${what}.to_user_id must name a user`);
    check(o.from_user_id !== o.to_user_id, `${what} must be between two different users`);
    check(isInt(o.amount) && o.amount >= 0 && o.amount <= MAX_AMOUNT, `${what}.amount must be an integer from 0 to ${MAX_AMOUNT}`);
    const visibility = o.visibility === undefined || o.visibility === null ? 'public' : o.visibility;
    check(typeof visibility === 'string' && VISIBILITIES.includes(visibility), `${what}.visibility must be public or private`);
    paymentIds.add(o.id as string);
    return {
      id: o.id as string, fromUserId: o.from_user_id as string, toUserId: o.to_user_id as string,
      amount: o.amount as number, note: optionalString(o.note, `${what}.note`),
      visibility: visibility as Visibility, requestId: optionalRef(o.request_id, `${what}.request_id`),
      settlementId: optionalRef(o.settlement_id, `${what}.settlement_id`),
      authorizationId: optionalRef(o.authorization_id, `${what}.authorization_id`),
    };
  });

  const requestIds = new Set<string>();
  const requests: SeedRequest[] = optionalArray(body, 'requests').map((r, i) => {
    const what = `requests[${i}]`;
    check(isObject(r), `${what} must be an object`);
    const o = r as JsonObject;
    check(isId(o.id) && !requestIds.has(o.id), `${what}.id must be a unique string of 1 to 64 characters`);
    check(typeof o.requester_id === 'string' && ids.has(o.requester_id), `${what}.requester_id must name a user`);
    check(typeof o.payer_id === 'string' && ids.has(o.payer_id), `${what}.payer_id must name a user`);
    check(o.requester_id !== o.payer_id, `${what} must be between two different users`);
    check(isInt(o.amount) && o.amount >= 0 && o.amount <= MAX_AMOUNT, `${what}.amount must be an integer from 0 to ${MAX_AMOUNT}`);
    const status = o.status === undefined || o.status === null ? 'pending' : o.status;
    check(typeof status === 'string' && REQUEST_STATUSES.includes(status), `${what}.status must be a request status`);
    requestIds.add(o.id as string);
    return {
      id: o.id as string, requesterId: o.requester_id as string, payerId: o.payer_id as string,
      amount: o.amount as number, note: optionalString(o.note, `${what}.note`),
      status: status as RequestStatus, paymentId: optionalRef(o.payment_id, `${what}.payment_id`),
    };
  });

  const operators = optionalArray(body, 'settlement_operator_ids').map((id, i) => {
    check(typeof id === 'string' && ids.has(id), `settlement_operator_ids[${i}] must name a user`);
    return id as string;
  });

  // Present means an integral number of seconds from 1 to 10^10 (600.0 is 600; null is not absent).
  let ttl = DEFAULT_TTL;
  if (has(body, 'authorization_ttl_seconds')) {
    const v = body.authorization_ttl_seconds;
    check(isInt(v) && v >= 1 && v <= MAX_TTL, `authorization_ttl_seconds must be an integer from 1 to ${MAX_TTL}`);
    ttl = v as number;
  }

  const authorizationIds = new Set<string>();
  const held = new Map<string, number>(); // payer id -> remainders still open at the reset's time
  const authorizations: SeedAuthorization[] = optionalArray(body, 'authorizations').map((a, i) => {
    const what = `authorizations[${i}]`;
    check(isObject(a), `${what} must be an object`);
    const o = a as JsonObject;
    check(isId(o.id) && !authorizationIds.has(o.id), `${what}.id must be a unique string of 1 to 64 characters`);
    check(typeof o.from_user_id === 'string' && ids.has(o.from_user_id), `${what}.from_user_id must name a user`);
    check(typeof o.to_user_id === 'string' && ids.has(o.to_user_id), `${what}.to_user_id must name a user`);
    check(o.from_user_id !== o.to_user_id, `${what} must be between two different users`);
    check(isInt(o.amount) && o.amount >= 0 && o.amount <= MAX_AMOUNT, `${what}.amount must be an integer from 0 to ${MAX_AMOUNT}`);
    const amount = o.amount as number;
    const status = absent(o.status) ? 'open' : o.status;
    check(typeof status === 'string' && AUTHORIZATION_STATUSES.includes(status), `${what}.status must be open, captured, voided or expired`);
    const captured = absent(o.captured_amount) ? (status === 'captured' ? amount : 0) : o.captured_amount;
    check(isInt(captured) && captured >= 0 && captured <= amount, `${what}.captured_amount must be an integer from 0 to amount`);
    check(status !== 'open' || (captured as number) < amount, `${what} is open and must leave something to capture`);
    const visibility = absent(o.visibility) ? 'public' : o.visibility;
    check(typeof visibility === 'string' && VISIBILITIES.includes(visibility), `${what}.visibility must be public or private`);
    const expiresAt = o.expires_at;
    const expiresMs = typeof expiresAt === 'string' && expiresAt.length <= 64 ? rfc3339Ms(expiresAt) : null;
    check(expiresMs !== null, `${what}.expires_at must be an RFC 3339 date-time of at most 64 characters`);
    // Display-only links, shown as given; each defaults from the other.
    check(has(o, 'payment_id') ? o.payment_id === null || typeof o.payment_id === 'string' : true,
      `${what}.payment_id must be a string or null`);
    check(absent(o.payment_ids) || (Array.isArray(o.payment_ids) && o.payment_ids.every((id) => typeof id === 'string')),
      `${what}.payment_ids must be an array of strings`);
    const paymentIds = absent(o.payment_ids)
      ? (typeof o.payment_id === 'string' ? [o.payment_id] : [])
      : [...(o.payment_ids as string[])];
    const paymentId = has(o, 'payment_id') ? (o.payment_id as string | null) : (paymentIds.at(-1) ?? null);
    if (status === 'open' && (expiresMs as number) > resetMs) {
      const from = o.from_user_id as string;
      held.set(from, (held.get(from) ?? 0) + amount - (captured as number));
    }
    authorizationIds.add(o.id as string);
    return {
      id: o.id as string, fromUserId: o.from_user_id as string, toUserId: o.to_user_id as string,
      amount, capturedAmount: captured as number, note: optionalString(o.note, `${what}.note`),
      visibility: visibility as Visibility, status: status as AuthorizationStatus,
      expiresAt: expiresAt as string, expiresMs: expiresMs as number, paymentId, paymentIds,
    };
  });
  for (const u of users) {
    check((held.get(u.id) ?? 0) <= u.balance, `the open authorizations of ${u.id} hold more than its balance`);
  }

  return {
    currency: body.currency as string, minorUnits: body.minor_units as number, ttl,
    users, payments, requests, authorizations, operators,
  };
}

// Hash every seeded password, then assemble the state, whose clock starts at the reset's own
// time (D49). Nothing here touches the live state.
export async function buildState(fixture: Fixture, resetMs: number): Promise<State> {
  const hashes = await Promise.all(fixture.users.map((u) => hashPassword(u.password, SEED_COST)));
  const st = emptyState();
  st.currency = fixture.currency;
  st.minorUnits = fixture.minorUnits;
  st.authorizationTtl = fixture.ttl;
  st.lastTs = formatTs(resetMs);
  fixture.users.forEach((u, i) => {
    addUser(st, {
      id: u.id, email: u.email, emailKey: emailKey(u.email), password: hashes[i],
      displayName: u.displayName, handle: u.handle, balance: u.balance, seq: nextSeq(st),
    });
  });
  // Seeded records take the reset's time; fixture order is creation order (D15). A seeded
  // authorization that is already closed closed at that time too; an open one past its
  // deadline reads expired at once.
  const ts = st.lastTs;
  for (const p of fixture.payments) {
    addPayment(st, { ...p, createdAt: ts, seq: nextSeq(st) });
  }
  for (const r of fixture.requests) {
    addRequest(st, { ...r, createdAt: ts, seq: nextSeq(st) });
  }
  for (const a of fixture.authorizations) {
    addAuthorization(st, { ...a, createdAt: ts, closedAt: a.status === 'open' ? null : ts, seq: nextSeq(st) });
  }
  for (const id of fixture.operators) st.operators.add(id);
  return st;
}
