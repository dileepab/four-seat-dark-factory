// GET /statement (plan 3.6, 3.9, D72, D73): the caller's payments in a half-open window of
// effective time, oldest first, with the running balance; every first read stores a snapshot
// that later pages read back exactly.

import { authenticate, instantParam, rawParam, type Ctx, type Result } from '../context.ts';
import { invalid, notFound } from '../errors.ts';
import { paging } from '../fields.ts';
import { deltaFor, selectRevision } from '../history.ts';
import { msKey } from '../instant.ts';
import { clock, formatTs, newId, store, type Payment, type Revision, type Snapshot, type State } from '../state.ts';
import { paymentView } from '../views.ts';

interface Entry {
  payment: Payment;
  revision: Revision;
  delta: number;
}

export function statement(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const st = store.state;
  let snapshot: Snapshot;
  let page: { limit: number; offset: number };
  if (rawParam(ctx, 'snapshot') !== undefined) {
    for (const name of ['from', 'to', 'known_at']) {
      if (rawParam(ctx, name) !== undefined) throw invalid(`${name} cannot be sent with a snapshot`);
    }
    page = paging(ctx.query);
    const found = st.snapshots.get(rawParam(ctx, 'snapshot') ?? '');
    if (found === undefined || found.ownerId !== caller.id) throw notFound('no such statement snapshot');
    snapshot = found;
  } else {
    const from = instantParam(ctx, 'from');
    const to = instantParam(ctx, 'to');
    const knownAt = instantParam(ctx, 'known_at');
    page = paging(ctx.query);
    // The read's instant R is its now; the default `to` is R plus a millisecond, so a payment
    // issued in the read's own millisecond is inside the window (plan 3.5, D67).
    const now = clock(st);
    const toText = to?.text ?? formatTs(now.ms + 1);
    const toKey = to?.key ?? msKey(now.ms + 1);
    // Only two given bounds can contradict; a later `from` with `to` omitted is an empty window
    // whose balances are both the balance at the read (D72).
    if (from !== null && to !== null && from.key > to.key) throw invalid('from must not be later than to');
    snapshot = {
      token: newId('ss', (id) => st.snapshots.has(id)),
      ownerId: caller.id,
      from: from?.text ?? null,
      fromKey: from?.key ?? null,
      to: toText,
      toKey,
      knownAt: knownAt?.text ?? null,
      knownKey: knownAt?.key ?? null,
      cutoff: st.seq,
    };
    st.snapshots.set(snapshot.token, snapshot);
  }
  return { status: 200, body: statementPage(st, snapshot, page.limit, page.offset) };
}

// The snapshot's whole result, recomputed in its view, and the requested page of it.
export function statementPage(st: State, s: Snapshot, limit: number, offset: number): Record<string, unknown> {
  const user = st.users.get(s.ownerId)!;
  const view = { K: s.knownKey, C: s.cutoff };
  let opening = user.opening;
  const entries: Entry[] = [];
  for (const payment of st.paymentsOf.get(user.id) ?? []) {
    const revision = selectRevision(payment, view);
    if (revision === null || revision.effKey >= s.toKey) continue;
    const delta = deltaFor(payment, user.id, revision.amount);
    if (s.fromKey !== null && revision.effKey < s.fromKey) opening += delta;
    else entries.push({ payment, revision, delta });
  }
  entries.sort((a, b) => (a.revision.effKey < b.revision.effKey ? -1 : a.revision.effKey > b.revision.effKey ? 1
    : byCodePoint(a.payment.id, b.payment.id)));
  let balance = opening;
  const shown: Record<string, unknown>[] = [];
  entries.forEach((e, i) => {
    balance += e.delta;
    if (i < offset || i >= offset + limit) return;
    shown.push({
      payment: { ...paymentView(st, e.payment), amount: e.revision.amount },
      delta: e.delta,
      balance_after: balance,
      revision: e.revision.revision,
      effective_at: e.revision.effectiveAt,
      recorded_at: e.revision.recordedAt,
    });
  });
  const body: Record<string, unknown> = {
    opening_balance: opening,
    entries: shown,
    closing_balance: balance,
    has_more: offset + limit < entries.length,
    snapshot: s.token,
  };
  if (s.knownAt !== null) body.known_at = s.knownAt;
  return body;
}

// Code-point order (D72): plain string comparison orders UTF-16 code units, which differs for
// characters beyond U+FFFF in a seeded id.
function byCodePoint(a: string, b: string): number {
  const ia = a[Symbol.iterator]();
  const ib = b[Symbol.iterator]();
  for (;;) {
    const ca = ia.next();
    const cb = ib.next();
    if (ca.done || cb.done) return (ca.done ? 0 : 1) - (cb.done ? 0 : 1);
    const diff = ca.value.codePointAt(0)! - cb.value.codePointAt(0)!;
    if (diff !== 0) return diff;
  }
}
