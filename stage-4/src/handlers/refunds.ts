// POST /payments/{id}/refunds (plan 3.9, D89-D93, D104): the receiver sends some of a payment
// back as a new payment, never more in all than the payment's latest amount.

import { authenticate, readJson, type Ctx, type Result } from '../context.ts';
import { ApiError, conflict, forbidden, invalid, notFound } from '../errors.ts';
import { requireAmount } from '../fields.ts';
import { idempotencyKey, idempotent } from '../idempotency.ts';
import { canCredit, commitTransfer } from '../ledger.ts';
import { availableOf, clock, issue } from '../state.ts';
import { paymentView } from '../views.ts';

export function refundPayment(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st) => {
    const now = clock(st);
    const amount = requireAmount(body);
    const target = st.paymentsById.get(ctx.params.id);
    if (!target) throw notFound('no such payment');
    if (target.toUserId !== caller.id) throw forbidden('only the receiver may refund this payment');
    if (target.refundOf !== null) throw new ApiError(422, 'invalid_refund_target', 'a refund cannot be refunded');
    const latest = target.revisions[target.revisions.length - 1];
    if (target.refunded + amount > latest.amount) {
      throw new ApiError(422, 'refund_exceeds_payment',
        `the payment's amount is ${latest.amount}, of which ${target.refunded} is refunded`);
    }
    // The money leaves the receiver's available funds (held funds cannot be refunded). A refund
    // takes effect at its own created_at, later than every effective time so far, so this
    // current check covers its history too (D104).
    if (availableOf(st, caller, now.ms) < amount) throw conflict('insufficient_funds', 'your available balance is below the amount');
    const sender = st.users.get(target.fromUserId)!;
    if (!canCredit(sender, amount)) throw invalid('the refund would take the payment\'s sender above 2^53');
    // Commit in this one synchronous step: a plain payment back, linked to nothing but its
    // target, so no request, authorization, hold or settlement changes (D91, D93).
    const refund = commitTransfer(st, {
      from: caller, to: sender, amount, note: target.note, visibility: target.visibility,
      requestId: null, settlementId: null, authorizationId: null, refundOf: target.id, createdAt: issue(st, now),
    });
    return paymentView(st, refund);
  });
}
