// The service state: one in-memory object, replaced wholesale by reset and import.
//
// Concurrency model (plan 3.13): every operation reads, checks and writes this state
// synchronously, with no await in between, so the event loop serializes them. Only
// password hashing is asynchronous, and code after it re-reads `store.state`.

import { randomBytes } from 'node:crypto';

export type Visibility = 'public' | 'private';
export type RequestStatus = 'pending' | 'paid' | 'declined' | 'cancelled';

export const VISIBILITIES: readonly string[] = ['public', 'private'];
export const REQUEST_STATUSES: readonly string[] = ['pending', 'paid', 'declined', 'cancelled'];

// The largest balance any operation may produce (spec §4: no balance outside ±2^53).
export const MAX_BALANCE = 2 ** 53;
export const MAX_AMOUNT = 1_000_000_000;

export interface PasswordHash {
  alg: 'scrypt';
  N: number;
  r: number;
  p: number;
  salt: string; // base64
  hash: string; // base64
}

export interface User {
  id: string;
  email: string;
  emailKey: string; // lower-cased email, the uniqueness and login key
  password: PasswordHash;
  displayName: string;
  handle: string;
  balance: number;
  seq: number;
}

export interface Payment {
  id: string;
  fromUserId: string;
  toUserId: string;
  amount: number;
  note: string;
  visibility: Visibility;
  requestId: string | null;
  settlementId: string | null;
  createdAt: string;
  seq: number;
}

export interface PayRequest {
  id: string;
  requesterId: string;
  payerId: string;
  amount: number;
  note: string;
  status: RequestStatus;
  paymentId: string | null;
  createdAt: string;
  seq: number;
}

export interface Share {
  handle: string;
  amount: number;
}

export interface Split {
  id: string;
  creatorId: string;
  amount: number;
  note: string;
  shares: Share[];
  requestIds: string[]; // one per participant other than the creator, in handle order
  createdAt: string;
  seq: number;
}

// A completed idempotent call: the parsed body and the exact response it produced.
export interface IdemRecord {
  userId: string;
  method: string;
  path: string;
  key: string;
  body: unknown;
  response: unknown;
}

export interface State {
  currency: string;
  minorUnits: number;
  users: Map<string, User>;
  usersByHandle: Map<string, User>;
  usersByEmail: Map<string, User>;
  tokens: Map<string, string>; // SHA-256 of the bearer token (hex) -> user id
  payments: Payment[]; // creation order
  paymentsById: Map<string, Payment>;
  requests: PayRequest[]; // creation order
  requestsById: Map<string, PayRequest>;
  splits: Map<string, Split>;
  operators: Set<string>;
  idem: Map<string, IdemRecord>; // see idempotency.ts for the map key
  seq: number; // creation counter, the tie-break for equal timestamps
  lastTs: string; // the latest timestamp issued
}

export function emptyState(): State {
  return {
    currency: 'EUR',
    minorUnits: 2,
    users: new Map(),
    usersByHandle: new Map(),
    usersByEmail: new Map(),
    tokens: new Map(),
    payments: [],
    paymentsById: new Map(),
    requests: [],
    requestsById: new Map(),
    splits: new Map(),
    operators: new Set(),
    idem: new Map(),
    seq: 0,
    lastTs: formatTs(Date.now()),
  };
}

// The one live state. Reset and import build a new State aside and swap it in here.
export const store: { state: State } = { state: emptyState() };

export function swapState(next: State): void {
  store.state = next;
}

// UTC, exactly three fractional digits, '+00:00': string order equals time order.
export function formatTs(ms: number): string {
  return new Date(ms).toISOString().replace('Z', '+00:00');
}

// A timestamp that is never earlier than any timestamp this state issued before.
export function nextTs(st: State): string {
  const now = formatTs(Date.now());
  if (now > st.lastTs) st.lastTs = now;
  return st.lastTs;
}

export function nextSeq(st: State): number {
  st.seq += 1;
  return st.seq;
}

// `<prefix>_<96 random bits>`, redrawn on the (theoretical) clash with an existing id.
export function newId(prefix: string, taken: (id: string) => boolean): string {
  for (;;) {
    const id = `${prefix}_${randomBytes(12).toString('base64url')}`;
    if (!taken(id)) return id;
  }
}

export function addUser(st: State, user: User): void {
  st.users.set(user.id, user);
  st.usersByHandle.set(user.handle, user);
  st.usersByEmail.set(user.emailKey, user);
}

export function addPayment(st: State, payment: Payment): void {
  st.payments.push(payment);
  st.paymentsById.set(payment.id, payment);
}

export function addRequest(st: State, request: PayRequest): void {
  st.requests.push(request);
  st.requestsById.set(request.id, request);
}
