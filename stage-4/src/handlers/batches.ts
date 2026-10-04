// POST /correction-batches (plan 3.9, D95-D100, D105): a settlement operator corrects several
// payments in one step, every settlement it touches whole, judged on the combined effect.

import { authenticate, readJson, type Ctx, type Result } from '../context.ts';
import { ApiError, conflict, forbidden, invalid, notFound } from '../errors.ts';
import { historyStaysCovered } from '../history.ts';
import { idempotencyKey, idempotent } from '../idempotency.ts';
import { msKey } from '../instant.ts';
import { isObject } from '../json.ts';
import {
  availableOf, clock, issue, MAX_BALANCE, newId, nextSeq, store, type Payment, type Revision, type User,
} from '../state.ts';
import { correctionFields, revisionView } from './corrections.ts';

const MAX_ITEMS = 32;

export function createCorrectionBatch(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  // As for settlements, permission depends only on the caller: settled before the key and body (D95).
  if (!store.state.operators.has(caller.id)) throw forbidden('only settlement operators may correct in batches');
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st) => {
    const now = clock(st);
    const nowKey = msKey(now.ms);

    // Step 7, the shape: 1 to 32 objects naming distinct payments, every element checked before
    // any item is examined.
    const raw = body.corrections;
    if (!Array.isArray(raw)) throw invalid('corrections must be an array');
    if (raw.length < 1 || raw.length > MAX_ITEMS) throw invalid(`corrections holds 1 to ${MAX_ITEMS} items`);
    const entries = raw.map((entry, i) => {
      if (!isObject(entry)) throw invalid(`corrections[${i}] must be an object`);
      return entry;
    });
    const named = new Set<string>();
    entries.forEach((entry, i) => {
      if (typeof entry.payment_id !== 'string') return;
      if (named.has(entry.payment_id)) throw invalid(`corrections[${i}] names payment ${entry.payment_id} again`);
      named.add(entry.payment_id);
    });

    // Step 8, each item in input order, the first failing one answering: its fields, its payment,
    // what that payment is, its revision, its refunds. An operator need not be a party (D96).
    const items = entries.map((entry, i) => {
      const what = `corrections[${i}].`;
      if (typeof entry.payment_id !== 'string') throw invalid(`${what}payment_id must be a string`);
      const fields = correctionFields(entry, nowKey, what);
      const payment = st.paymentsById.get(entry.payment_id);
      if (!payment) throw notFound(`corrections[${i}]: no such payment`);
      if (payment.authorizationId !== null || payment.refundOf !== null) {
        throw new ApiError(422, 'linked_payment_immutable', `corrections[${i}]: a capture or a refund cannot be corrected`);
      }
      const latest = payment.revisions[payment.revisions.length - 1];
      if (fields.expected !== latest.revision) {
        throw conflict('stale_revision', `corrections[${i}]: the payment's latest revision is ${latest.revision}`);
      }
      if (fields.amount < payment.refunded) {
        throw new ApiError(422, 'refund_exceeds_payment', `corrections[${i}]: the payment has ${payment.refunded} refunded`);
      }
      const proposed: Revision = {
        revision: latest.revision + 1, amount: fields.amount, effectiveAt: fields.effectiveAt, effKey: fields.effKey,
        recordedAt: '', recKey: '', reason: fields.reason, seq: 0, batchId: null,
      };
      return { payment, rise: fields.amount - latest.amount, proposed };
    });

    // Steps 9 and 10: every settlement the batch touches is in it whole, then its members take
    // effect at one instant, compared exactly whatever the spelling (D98).
    for (const { payment } of items) {
      if (payment.settlementId === null) continue;
      for (const member of st.membersOf.get(payment.settlementId)!) {
        if (!named.has(member.id)) {
          throw new ApiError(422, 'incomplete_settlement', `settlement ${payment.settlementId} has members outside the batch`);
        }
      }
    }
    const instants = new Map<string, string>();
    for (const { payment, proposed } of items) {
      if (payment.settlementId === null) continue;
      const first = instants.get(payment.settlementId);
      if (first === undefined) instants.set(payment.settlementId, proposed.effKey);
      else if (first !== proposed.effKey) {
        throw invalid(`the members of settlement ${payment.settlementId} must take effect at one instant`);
      }
    }

    // Steps 11 and 12: the combined difference per wallet, each moving between its payment's two
    // wallets, judged on current available funds (D99), then the 2^53 guard.
    const net = new Map<User, number>();
    for (const { payment, rise } of items) {
      const sender = st.users.get(payment.fromUserId)!;
      const receiver = st.users.get(payment.toUserId)!;
      net.set(sender, (net.get(sender) ?? 0) - rise);
      net.set(receiver, (net.get(receiver) ?? 0) + rise);
    }
    for (const [user, change] of net) {
      if (availableOf(st, user, now.ms) + change < 0) {
        throw conflict('insufficient_funds', `${user.handle} cannot cover the batch`);
      }
    }
    for (const [user, change] of net) {
      if (change > 0 && user.balance > MAX_BALANCE - change) throw invalid(`the batch would take ${user.handle} above 2^53`);
    }

    // Step 13: every party's history with all the new revisions applied together.
    const proposals = new Map<Payment, Revision>(items.map(({ payment, proposed }) => [payment, proposed]));
    for (const user of net.keys()) {
      if (!historyStaysCovered(st, user, nowKey, proposals)) {
        throw conflict('historical_overdraft', `the batch would overdraw ${user.handle} at an earlier instant`);
      }
    }

    // Commit in this one synchronous step: one recorded_at for every new revision (D100).
    const recordedAt = issue(st, now);
    const recKey = msKey(Date.parse(recordedAt));
    const id = newId('cb', (taken) => st.batchIds.has(taken));
    st.batchIds.add(id);
    for (const [payment, r] of proposals) {
      r.recordedAt = recordedAt;
      r.recKey = recKey;
      r.seq = nextSeq(st);
      r.batchId = id;
      payment.revisions.push(r);
    }
    for (const [user, change] of net) user.balance += change;
    return {
      correction_batch_id: id,
      recorded_at: recordedAt,
      revisions: items.map(({ payment, proposed }) => revisionView(payment, proposed)),
    };
  });
}
