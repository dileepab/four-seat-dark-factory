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
