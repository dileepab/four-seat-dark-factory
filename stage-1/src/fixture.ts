// POST /_test/reset: validate a fixture completely, then build the new state aside (plan 3.11).

import { invalid } from './errors.ts';
import { cpLength, emailKey, HANDLE_RE, isEmail } from './fields.ts';
import { isObject, type JsonObject } from './json.ts';
import { hashPassword, SEED_COST } from './passwords.ts';
import {
  addPayment, addRequest, addUser, emptyState, MAX_AMOUNT, MAX_BALANCE, nextSeq, nextTs,
  REQUEST_STATUSES, VISIBILITIES,
  type RequestStatus, type State, type Visibility,
} from './state.ts';

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

interface Fixture {
  currency: string;
  minorUnits: number;
  users: SeedUser[];
  payments: SeedPayment[];
  requests: SeedRequest[];
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

export function validateFixture(body: JsonObject): Fixture {
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

  return { currency: body.currency as string, minorUnits: body.minor_units as number, users, payments, requests, operators };
}

// Hash every seeded password, then assemble the state. Nothing here touches the live state.
export async function buildState(fixture: Fixture): Promise<State> {
  const hashes = await Promise.all(fixture.users.map((u) => hashPassword(u.password, SEED_COST)));
  const st = emptyState();
  st.currency = fixture.currency;
  st.minorUnits = fixture.minorUnits;
  fixture.users.forEach((u, i) => {
    addUser(st, {
      id: u.id, email: u.email, emailKey: emailKey(u.email), password: hashes[i],
      displayName: u.displayName, handle: u.handle, balance: u.balance, seq: nextSeq(st),
    });
  });
  // Seeded records take the reset's time; fixture order is creation order (D15).
  const ts = nextTs(st);
  for (const p of fixture.payments) {
    addPayment(st, { ...p, createdAt: ts, seq: nextSeq(st) });
  }
  for (const r of fixture.requests) {
    addRequest(st, { ...r, createdAt: ts, seq: nextSeq(st) });
  }
  for (const id of fixture.operators) st.operators.add(id);
  return st;
}
