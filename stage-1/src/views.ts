// Response representations (plan 3.6): exactly these fields, identical wherever they appear.

import type { PayRequest, Payment, Split, State } from './state.ts';

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
