// The service state: one in-memory object, replaced wholesale by reset and import.
//
// Concurrency model (plan 3.13): every operation reads, checks and writes this state
// synchronously, with no await in between, so the event loop serializes them. Only
// password hashing is asynchronous, and code after it re-reads `store.state`.

import { randomBytes } from 'node:crypto';
import { tsKey } from './instant.ts';

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
  balance: number; // the current total, every payment at its latest revision
  opening: number; // the balance before any of the user's payments (plan 3.7); never changes
  seq: number;
}

// One revision of a payment (plan 3.7): revision 1 is the payment as made, every later one a
// correction. Revisions are only ever appended.
export interface Revision {
  revision: number;
  amount: number;
  effectiveAt: string; // exactly as given (or the payment's created_at for revision 1)
  effKey: string; // instant.ts key of effectiveAt
  recordedAt: string; // issued by the service
  recKey: string;
  reason: string; // "" for revision 1
  seq: number; // the creation sequence when it was recorded (D70)
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
  createdAt: string; // as issued, or exactly as seeded
  createdKey: string; // instant.ts key of createdAt
  revisions: Revision[]; // 1..n; `amount` above is revision 1's
  seq: number;
}

export type NewPayment = Omit<Payment, 'createdKey' | 'revisions'> & { revisions?: Revision[] };

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
  expiresKey: string; // its exact instant (instant.ts), for historical views
  paymentId: string | null; // the latest capture
  paymentIds: string[]; // every capture, in order
  createdAt: string; // as issued, or exactly as seeded
  createdKey: string;
  closedAt: string | null; // when a void or a capture closed it; null while open and for clock expiry
  closedKey: string | null; // its exact instant
  // Seeded as captured, voided or expired: it holds nothing at any instant (plan 3.8, D71).
  seededClosed: boolean;
  // Captured before its history starts (a seeded captured_amount without capture payments):
  // counted from creation. Captures made through the API are payments (capturesOf).
  baseCaptured: number;
  seq: number;
}

export type NewAuthorization = Omit<Authorization, 'expiresKey' | 'createdKey' | 'closedKey'>;

// A statement's frozen result (plan 3.9, D73): its owner, window, known_at and the creation
// sequence at its first read. Revisions are only appended, so recomputing the view gives the
// same entries and balances at any later time; no entries are stored.
export interface Snapshot {
  token: string;
  ownerId: string;
  from: string | null; // as given; null for the wallet's opening
  fromKey: string | null;
  to: string; // as given, or the defaulted instant (the read's now plus a millisecond)
  toKey: string;
  knownAt: string | null; // as given
  knownKey: string | null;
  cutoff: number;
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
  paymentsOf: Map<string, Payment[]>; // user id -> the payments they sent or received
  capturesOf: Map<string, Payment[]>; // authorization id -> the payments linked to it
  authorizationsOf: Map<string, Authorization[]>; // payer id -> their authorizations
  snapshots: Map<string, Snapshot>; // statement token -> its frozen view
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
    paymentsOf: new Map(),
    capturesOf: new Map(),
    authorizationsOf: new Map(),
    snapshots: new Map(),
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

// A timestamp strictly later than every timestamp this state issued before (D67): the wall
// clock, or the last issued one plus a millisecond when the wall clock has not moved past it.
export function nextTs(st: State): string {
  return issue(st, clock(st));
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

// Issue the write's one timestamp (D67): the operation's `now` when it is later than the last
// issued timestamp, else that one plus a millisecond. Every record of the write shares it.
export function issue(st: State, now: Now): string {
  st.lastTs = now.ts > st.lastTs ? now.ts : formatTs(Date.parse(st.lastTs) + 1);
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

function indexed<K, V>(map: Map<K, V[]>, key: K): V[] {
  let list = map.get(key);
  if (!list) map.set(key, (list = []));
  return list;
}

// Add a payment; without `revisions` it gets revision 1 from its own fields (plan 3.7).
export function addPayment(st: State, input: NewPayment): Payment {
  const createdKey = tsKey(input.createdAt);
  const payment: Payment = {
    ...input,
    createdKey,
    revisions: input.revisions ?? [{
      revision: 1, amount: input.amount, effectiveAt: input.createdAt, effKey: createdKey,
      recordedAt: input.createdAt, recKey: createdKey, reason: '', seq: input.seq,
    }],
  };
  st.payments.push(payment);
  st.paymentsById.set(payment.id, payment);
  indexed(st.paymentsOf, payment.fromUserId).push(payment);
  if (payment.toUserId !== payment.fromUserId) indexed(st.paymentsOf, payment.toUserId).push(payment);
  if (payment.authorizationId !== null) indexed(st.capturesOf, payment.authorizationId).push(payment);
  return payment;
}

export function addRequest(st: State, request: PayRequest): void {
  st.requests.push(request);
  st.requestsById.set(request.id, request);
}

export function addAuthorization(st: State, input: NewAuthorization): Authorization {
  const a: Authorization = {
    ...input,
    createdKey: tsKey(input.createdAt),
    expiresKey: tsKey(input.expiresAt),
    closedKey: input.closedAt === null ? null : tsKey(input.closedAt),
  };
  st.authorizations.push(a);
  st.authorizationsById.set(a.id, a);
  indexed(st.authorizationsOf, a.fromUserId).push(a);
  if (a.status === 'open') {
    let open = st.holds.get(a.fromUserId);
    if (!open) st.holds.set(a.fromUserId, (open = new Set()));
    open.add(a);
  }
  return a;
}

// Records seeded or imported with earlier instants than records made after them: put the
// record arrays in time order (instant, then creation), as every list reads them newest first.
// Records made afterwards always carry the latest instant (D67), so appending keeps the order.
export function sortByTime(st: State): void {
  const order = (a: { createdKey: string; seq: number }, b: { createdKey: string; seq: number }) =>
    (a.createdKey < b.createdKey ? -1 : a.createdKey > b.createdKey ? 1 : a.seq - b.seq);
  st.payments.sort(order);
  st.authorizations.sort(order);
  st.requests.sort((a, b) => {
    const ka = tsKey(a.createdAt);
    const kb = tsKey(b.createdAt);
    return ka < kb ? -1 : ka > kb ? 1 : a.seq - b.seq;
  });
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
  a.closedKey = tsKey(ts);
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
