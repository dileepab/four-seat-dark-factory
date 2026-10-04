// Response representations (plan 3.6): exactly these fields, identical wherever they appear.

import {
  remainingAt, statusAt,
  type Authorization, type PayRequest, type Payment, type Split, type State,
} from './state.ts';

function handleOf(st: State, userId: string): string {
  return st.users.get(userId)?.handle ?? '';
}

export function paymentView(st: State, p: Payment): Record<string, unknown> {
  return {
    payment_id: p.id,
    from_user_id: p.fromUserId,
    from_handle: handleOf(st, p.fromUserId),
    to_user_id: p.toUserId,
    to_handle: handleOf(st, p.toUserId),
    amount: p.amount,
    currency: st.currency,
    note: p.note,
    visibility: p.visibility,
    request_id: p.requestId,
    settlement_id: p.settlementId,
    authorization_id: p.authorizationId,
    created_at: p.createdAt,
  };
}

export function requestView(st: State, r: PayRequest): Record<string, unknown> {
  return {
    request_id: r.id,
    requester_id: r.requesterId,
    requester_handle: handleOf(st, r.requesterId),
    payer_id: r.payerId,
    payer_handle: handleOf(st, r.payerId),
    amount: r.amount,
    currency: st.currency,
    note: r.note,
    status: r.status,
    payment_id: r.paymentId,
    created_at: r.createdAt,
  };
}

export function splitView(st: State, s: Split): Record<string, unknown> {
  return {
    split_id: s.id,
    amount: s.amount,
    currency: st.currency,
    note: s.note,
    shares: s.shares.map((share) => ({ handle: share.handle, amount: share.amount })),
    requests: s.requestIds.map((id) => requestView(st, st.requestsById.get(id)!)),
    created_at: s.createdAt,
  };
}

// The authorization as a read at `nowMs` sees it (plan 3.6, D51).
export function authorizationView(st: State, a: Authorization, nowMs: number): Record<string, unknown> {
  return {
    authorization_id: a.id,
    from_user_id: a.fromUserId,
    from_handle: handleOf(st, a.fromUserId),
    to_user_id: a.toUserId,
    to_handle: handleOf(st, a.toUserId),
    amount: a.amount,
    captured_amount: a.capturedAmount,
    remaining_amount: remainingAt(a, nowMs),
    currency: st.currency,
    note: a.note,
    visibility: a.visibility,
    status: statusAt(a, nowMs),
    expires_at: a.expiresAt,
    payment_id: a.paymentId,
    payment_ids: [...a.paymentIds],
    created_at: a.createdAt,
  };
}

// One page of `items` (creation order) newest first: skip `offset` matches, take `limit`.
export function newestFirst<T>(
  items: readonly T[], keep: (item: T) => boolean, limit: number, offset: number,
): { page: T[]; hasMore: boolean } {
  const page: T[] = [];
  let matched = 0;
  for (let i = items.length - 1; i >= 0; i--) {
    if (!keep(items[i])) continue;
    if (matched >= offset + limit) return { page, hasMore: true };
    if (matched >= offset) page.push(items[i]);
    matched++;
  }
  return { page, hasMore: false };
}
