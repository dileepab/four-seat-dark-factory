// The service state: one in-memory object, replaced wholesale by reset and import.
//
// Concurrency model (plan 3.13): every operation reads, checks and writes this state
// synchronously, with no await in between, so the event loop serializes them. Only
// password hashing is asynchronous, and code after it re-reads `store.state`.

import { randomBytes } from 'node:crypto';

export type Visibility = 'public' | 'private';
export type RequestStatus = 'pending' | 'paid' | 'declined' | 'cancelled';
export type AuthorizationStatus = 'open' | 'captured' | 'voided' | 'expired';

export const VISIBILITIES: readonly string[] = ['public', 'private'];
export const REQUEST_STATUSES: readonly string[] = ['pending', 'paid', 'declined', 'cancelled'];
export const AUTHORIZATION_STATUSES: readonly string[] = ['open', 'captured', 'voided', 'expired'];

// The largest balance any operation may produce (spec §4: no balance outside ±2^53).
export const MAX_BALANCE = 2 ** 53;
export const MAX_AMOUNT = 1_000_000_000;
export const DEFAULT_TTL = 600; // seconds, before any reset sets authorization_ttl_seconds
export const MAX_TTL = 10_000_000_000;

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
  authorizationId: string | null; // the authorization a capture took this payment from
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

export interface Settlement {
  id: string;
  operatorId: string;
  committedAt: string;
  paymentIds: string[]; // members, in input order
  seq: number;
}

// A hold on the payer's wallet (stage-2 "Authorizations and captures"). The stored status is
// what an event set; an open authorization whose expiry has passed reads `expired` (statusAt).
export interface Authorization {
  id: string;
  fromUserId: string; // the payer, whose funds are held
  toUserId: string; // the receiver, who captures
  amount: number;
  capturedAmount: number;
  note: string;
  visibility: Visibility;
  status: AuthorizationStatus;
  expiresAt: string; // exactly as issued or seeded
  expiresMs: number; // its instant, whole milliseconds rounded up (time.ts)
  paymentId: string | null; // the latest capture
  paymentIds: string[]; // every capture, in order
  createdAt: string;
  closedAt: string | null; // when a void or a capture closed it; null while open and for clock expiry
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
  settlements: Map<string, Settlement>;
  authorizationTtl: number; // seconds
  authorizations: Authorization[]; // creation order
  authorizationsById: Map<string, Authorization>;
  holds: Map<string, Set<Authorization>>; // payer id -> stored-open authorizations (see heldBy)
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
    settlements: new Map(),
    authorizationTtl: DEFAULT_TTL,
    authorizations: [],
    authorizationsById: new Map(),
    holds: new Map(),
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

// The service clock (D49): the later of the wall clock and the last issued timestamp. Every
// operation, reads included, takes it once at its start and judges expiry by it. Reading it
// changes nothing; only a commit issues its time (`issue`), as nextTs does.
export interface Now {
  ts: string;
  ms: number;
}

export function clock(st: State): Now {
  const wall = formatTs(Date.now());
  const ts = wall > st.lastTs ? wall : st.lastTs;
  return { ts, ms: Date.parse(ts) };
}

// Record the operation's `now` as issued (it is never earlier than lastTs) and return it.
export function issue(st: State, now: Now): string {
  if (now.ts > st.lastTs) st.lastTs = now.ts;
  return now.ts;
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

export function addAuthorization(st: State, a: Authorization): void {
  st.authorizations.push(a);
  st.authorizationsById.set(a.id, a);
  if (a.status === 'open') {
    let open = st.holds.get(a.fromUserId);
    if (!open) st.holds.set(a.fromUserId, (open = new Set()));
    open.add(a);
  }
}

// The status a read at `nowMs` shows: an open authorization is expired from its deadline on.
export function statusAt(a: Authorization, nowMs: number): AuthorizationStatus {
  return a.status === 'open' && nowMs >= a.expiresMs ? 'expired' : a.status;
}

// What the authorization still holds at `nowMs`: the uncaptured remainder while open, else 0.
export function remainingAt(a: Authorization, nowMs: number): number {
  return statusAt(a, nowMs) === 'open' ? a.amount - a.capturedAmount : 0;
}

// Close an open authorization (a final or full capture, or a void): it holds nothing from now on.
export function closeAuthorization(st: State, a: Authorization, status: 'captured' | 'voided', ts: string): void {
  a.status = status;
  a.closedAt = ts;
  st.holds.get(a.fromUserId)?.delete(a);
}

// The sum of the user's open holds at `nowMs`. An authorization past its deadline holds
// nothing; once the last issued timestamp has passed the deadline it never can again (every
// later clock reading is at least that), so it leaves the index. Its stored status stays
// `open` (closed_at null: the deadline is its closing time).
export function heldBy(st: State, userId: string, nowMs: number): number {
  const open = st.holds.get(userId);
  if (!open) return 0;
  const floor = Date.parse(st.lastTs);
  let held = 0;
  for (const a of open) {
    if (a.expiresMs <= floor) open.delete(a);
    else if (a.expiresMs > nowMs) held += a.amount - a.capturedAmount;
  }
  return held;
}

// What the user can spend at `nowMs`: total minus held, never negative (I30, I31).
export function availableOf(st: State, user: User, nowMs: number): number {
  return user.balance - heldBy(st, user.id, nowMs);
}
