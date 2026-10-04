// POST /payments and GET /activity (spec §4 feed contract, §8).

import { authenticate, readJson, type Ctx, type Result } from '../context.ts';
import { ApiError, conflict, invalid, notFound } from '../errors.ts';
import { optionalNote, optionalVisibility, paging, requireAmount, requireHandle } from '../fields.ts';
import { idempotencyKey, idempotent } from '../idempotency.ts';
import { canCredit, commitTransfer } from '../ledger.ts';
import { availableOf, clock, issue, store } from '../state.ts';
import { newestFirst, paymentView } from '../views.ts';

export function createPayment(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st) => {
    const toHandle = requireHandle(body, 'to_handle');
    const amount = requireAmount(body);
    const note = optionalNote(body);
    const visibility = optionalVisibility(body);
    const to = st.usersByHandle.get(toHandle);
    if (!to) throw notFound('no user has that handle');
    if (to.id === caller.id) throw new ApiError(422, 'self_payment', 'you cannot pay yourself');
    const now = clock(st);
    if (availableOf(st, caller, now.ms) < amount) throw conflict('insufficient_funds', 'your available balance is below the amount');
    if (!canCredit(to, amount)) throw invalid('the payment would take the receiver above 2^53');
    const payment = commitTransfer(st, {
      from: caller, to, amount, note, visibility, requestId: null, settlementId: null, authorizationId: null,
      createdAt: issue(st, now),
    });
    return paymentView(st, payment);
  });
}

// A payment appears iff it is public or the caller is its sender or receiver.
export function activity(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const { limit, offset } = paging(ctx.query);
  const st = store.state;
  const { page, hasMore } = newestFirst(
    st.payments,
    (p) => p.visibility === 'public' || p.fromUserId === caller.id || p.toUserId === caller.id,
    limit, offset,
  );
  return { status: 200, body: { payments: page.map((p) => paymentView(st, p)), has_more: hasMore } };
}
