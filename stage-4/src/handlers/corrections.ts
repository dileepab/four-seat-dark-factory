// POST /payments/{id}/corrections and GET /payments/{id}/revisions (plan 3.9, D74, D75, D80-D83, D94).

import { authenticate, readJson, type Ctx, type Result } from '../context.ts';
import { ApiError, conflict, forbidden, invalid, notFound } from '../errors.ts';
import { cpLength } from '../fields.ts';
import { historyStaysCovered } from '../history.ts';
import { idempotencyKey, idempotent } from '../idempotency.ts';
import { has, type JsonObject } from '../json.ts';
import { canCredit } from '../ledger.ts';
import { instantKey, msKey } from '../instant.ts';
import {
  availableOf, clock, issue, MAX_AMOUNT, MAX_BALANCE, nextSeq, store, type Payment, type Revision, type State,
} from '../state.ts';

const MAX_REASON = 200;

// Stage 3's six fields, and the batch id on a revision a correction batch recorded (D97).
export function revisionView(p: Payment, r: Revision): Record<string, unknown> {
  const view: Record<string, unknown> = {
    payment_id: p.id,
    revision: r.revision,
    amount: r.amount,
    effective_at: r.effectiveAt,
    recorded_at: r.recordedAt,
    reason: r.reason,
  };
  if (r.batchId !== null) view.correction_batch_id = r.batchId;
  return view;
}

function integral(value: unknown, min: number, max: number): boolean {
  return typeof value === 'number' && Number.isInteger(value) && value >= min && value <= max;
}

// Step 6: every field rule, all 422 (D80); a batch checks each item by the same rules, its
// messages prefixed with the item (`what`).
export function correctionFields(body: JsonObject, nowKey: string, what = '') {
  for (const name of ['expected_revision', 'amount', 'effective_at', 'reason']) {
    if (!has(body, name) || body[name] === null) throw invalid(`${what}${name} is required`);
  }
  if (!integral(body.expected_revision, 1, MAX_BALANCE)) throw invalid(`${what}expected_revision must be an integer from 1 to 2^53`);
  if (!integral(body.amount, 0, MAX_AMOUNT)) throw invalid(`${what}amount must be an integer from 0 to ${MAX_AMOUNT}`);
  const effKey = instantKey(body.effective_at);
  if (effKey === null) throw invalid(`${what}effective_at must be an RFC 3339 instant with an offset, at most 64 characters`);
  if (effKey > nowKey) throw invalid(`${what}effective_at must not be later than now`);
  const reason = body.reason;
  if (typeof reason !== 'string' || cpLength(reason) < 1 || cpLength(reason) > MAX_REASON) {
    throw invalid(`${what}reason must be a string of 1 to ${MAX_REASON} characters`);
  }
  return {
    expected: body.expected_revision as number, amount: body.amount as number,
    effectiveAt: body.effective_at as string, effKey, reason,
  };
}

export function correctPayment(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st: State) => {
    const now = clock(st);
    const nowKey = msKey(now.ms);
    const fields = correctionFields(body, nowKey);
    const payment = st.paymentsById.get(ctx.params.id);
    if (!payment) throw notFound('no such payment');
    if (payment.fromUserId !== caller.id) throw forbidden('only the sender may correct this payment');
    if (payment.authorizationId !== null || payment.settlementId !== null || payment.refundOf !== null) {
      throw new ApiError(422, 'linked_payment_immutable', 'a capture, a settlement member or a refund cannot be corrected');
    }
    const latest = payment.revisions[payment.revisions.length - 1];
    if (fields.expected !== latest.revision) {
      throw conflict('stale_revision', `the payment's latest revision is ${latest.revision}`);
    }
    // Refunds only ever add up, so no correction may go below what was refunded (D92, D94).
    if (fields.amount < payment.refunded) {
      throw new ApiError(422, 'refund_exceeds_payment', `the payment has ${payment.refunded} refunded`);
    }
    // The difference moves between the same two wallets: a rise from the sender, a fall from
    // the receiver, judged on the debited party's current available (D53, D74).
    const sender = st.users.get(payment.fromUserId)!;
    const receiver = st.users.get(payment.toUserId)!;
    const rise = fields.amount - latest.amount;
    const [debited, credited] = rise >= 0 ? [sender, receiver] : [receiver, sender];
    const moved = Math.abs(rise);
    if (moved > availableOf(st, debited, now.ms)) {
      throw conflict('insufficient_funds', 'the debited wallet\'s available balance is below the difference');
    }
    if (!canCredit(credited, moved)) throw invalid('the correction would take the credited wallet above 2^53');
    const proposed: Revision = {
      revision: latest.revision + 1, amount: fields.amount, effectiveAt: fields.effectiveAt, effKey: fields.effKey,
      recordedAt: '', recKey: '', reason: fields.reason, seq: 0, batchId: null,
    };
    for (const party of [sender, receiver]) {
      if (!historyStaysCovered(st, party, nowKey, new Map([[payment, proposed]]))) {
        throw conflict('historical_overdraft', 'the correction would overdraw a wallet at an earlier instant');
      }
    }
    // Commit in this one synchronous step.
    proposed.recordedAt = issue(st, now);
    proposed.recKey = msKey(Date.parse(proposed.recordedAt));
    proposed.seq = nextSeq(st);
    payment.revisions.push(proposed);
    debited.balance -= moved;
    credited.balance += moved;
    return revisionView(payment, proposed);
  });
}

// GET /payments/{id}/revisions: only the two parties; anyone else, like an unknown payment, 404.
export function listRevisions(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const payment = store.state.paymentsById.get(ctx.params.id);
  if (!payment || (payment.fromUserId !== caller.id && payment.toUserId !== caller.id)) {
    throw notFound('no such payment');
  }
  return { status: 200, body: { revisions: payment.revisions.map((r) => revisionView(payment, r)) } };
}
