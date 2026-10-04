// Historical views (plan 3.7, 3.8, D70, D71): balances and holds as they stood at an
// effective instant T, as known at K, among the records created up to sequence C.

import type { Authorization, Payment, Revision, State, User } from './state.ts';

export interface View {
  T: string; // effective-time limit, an instant key, inclusive
  K: string | null; // known-at limit, an instant key, inclusive; null applies no time test
  C: number; // creation-sequence cutoff, inclusive
}

// The payment's revision in the view: its highest revision recorded at or before K (when K is
// given) and by sequence C. null when the view knows none of it.
export function selectRevision(p: Payment, view: Pick<View, 'K' | 'C'>): Revision | null {
  for (let i = p.revisions.length - 1; i >= 0; i--) {
    const r = p.revisions[i];
    if (r.seq <= view.C && (view.K === null || r.recKey <= view.K)) return r;
  }
  return null;
}

// What the payment moves for `userId` at the given revision: negative when sent.
export function deltaFor(p: Payment, userId: string, amount: number): number {
  return p.fromUserId === userId ? -amount : amount;
}

// total(T, K): the opening balance plus every selected revision in effect at T.
export function totalIn(st: State, user: User, view: View): number {
  let total = user.opening;
  for (const p of st.paymentsOf.get(user.id) ?? []) {
    const r = selectRevision(p, view);
    if (r !== null && r.effKey <= view.T) total += deltaFor(p, user.id, r.amount);
  }
  return total;
}

// What one of the user's outgoing authorizations holds in the view (plan 3.8).
export function holdIn(st: State, a: Authorization, view: View): number {
  if (a.seededClosed) return 0;
  const known = (key: string) => key <= view.T && (view.K === null || key <= view.K);
  if (a.seq > view.C || !known(a.createdKey)) return 0;
  let captured = a.baseCaptured;
  for (const p of st.capturesOf.get(a.id) ?? []) {
    if (p.seq <= view.C && known(p.createdKey)) captured += p.amount;
  }
  if (a.closedKey !== null && known(a.closedKey)) return 0;
  if (a.expiresKey <= view.T) return 0;
  return Math.max(0, a.amount - captured);
}

// held(T, K): the sum over the user's outgoing authorizations.
export function heldIn(st: State, user: User, view: View): number {
  let held = 0;
  for (const a of st.authorizationsOf.get(user.id) ?? []) held += holdIn(st, a, view);
  return held;
}

// Whether the user's total and available stay at or above 0 at every instant up to `nowKey`
// at which one of their payments takes effect or one of their holds changes, under the latest
// revisions, with `replace` standing in for its payment's latest; the movements of one instant
// are combined first (plan 3.9 step 13, I58).
export function historyStaysCovered(
  st: State, user: User, nowKey: string, replace: { payment: Payment; revision: Revision } | null,
): boolean {
  const events: { key: string; total: number; held: number }[] = [];
  for (const p of st.paymentsOf.get(user.id) ?? []) {
    const r = replace !== null && replace.payment === p ? replace.revision : p.revisions[p.revisions.length - 1];
    events.push({ key: r.effKey, total: deltaFor(p, user.id, r.amount), held: 0 });
  }
  // A hold changes only at its creation, its captures, its close and its deadline: record the
  // change in what it holds at each of those instants.
  for (const a of st.authorizationsOf.get(user.id) ?? []) {
    if (a.seededClosed) continue;
    const points = [a.createdKey, a.expiresKey, ...(st.capturesOf.get(a.id) ?? []).map((p) => p.createdKey)];
    if (a.closedKey !== null) points.push(a.closedKey);
    let previous = 0;
    for (const key of new Set(points.sort())) {
      const holding = holdIn(st, a, { T: key, K: null, C: Number.MAX_SAFE_INTEGER });
      if (holding !== previous) events.push({ key, total: 0, held: holding - previous });
      previous = holding;
    }
  }
  events.sort((x, y) => (x.key < y.key ? -1 : x.key > y.key ? 1 : 0));
  let total = user.opening;
  let held = 0;
  for (let i = 0; i < events.length && events[i].key <= nowKey;) {
    const key = events[i].key;
    for (; i < events.length && events[i].key === key; i++) {
      total += events[i].total;
      held += events[i].held;
    }
    if (total < 0 || total - held < 0) return false;
  }
  return true;
}
