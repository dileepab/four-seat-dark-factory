// POST /settlements (spec §11): an operator's batch of transfers, all or nothing, judged
// on each wallet's net position.

import { authenticate, readJson, type Ctx, type Result } from '../context.ts';
import { ApiError, conflict, forbidden, invalid, notFound } from '../errors.ts';
import { amountValue, optionalNote, optionalVisibility } from '../fields.ts';
import { idempotencyKey, idempotent } from '../idempotency.ts';
import { has, isObject, type JsonObject } from '../json.ts';
import { recordPayment, type Transfer } from '../ledger.ts';
import { availableOf, clock, MAX_BALANCE, newId, nextSeq, store, type State, type User } from '../state.ts';
import { paymentView } from '../views.ts';

const MAX_TRANSFERS = 32;

// One transfer entry by the ordinary payment rules. Malformed input inside the batch is
// 422, never 400 (D27); then unknown handles (404), then a self-transfer.
function readTransfer(st: State, entry: JsonObject, i: number): Omit<Transfer, 'settlementId' | 'createdAt'> {
  const fromHandle = handleField(entry, 'from_handle', i);
  const toHandle = handleField(entry, 'to_handle', i);
  if (!has(entry, 'amount')) throw invalid(`transfers[${i}].amount is required`);
  const amount = amountValue(entry.amount, `transfers[${i}].amount`);
  const note = optionalNote(entry);
  const visibility = optionalVisibility(entry);
  const from = st.usersByHandle.get(fromHandle);
  if (!from) throw notFound(`transfers[${i}]: no user has the handle ${fromHandle}`);
  const to = st.usersByHandle.get(toHandle);
  if (!to) throw notFound(`transfers[${i}]: no user has the handle ${toHandle}`);
  if (from.id === to.id) throw new ApiError(422, 'self_payment', `transfers[${i}] pays its own sender`);
  return { from, to, amount, note, visibility, requestId: null, authorizationId: null };
}

function handleField(entry: JsonObject, name: string, i: number): string {
  const value = entry[name];
  if (typeof value !== 'string') throw invalid(`transfers[${i}].${name} must be a string`);
  return value;
}

export function createSettlement(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  // Permission depends only on the caller, so it is settled before the key and body (D18).
  if (!store.state.operators.has(caller.id)) throw forbidden('only settlement operators may settle');
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st) => {
    // The batch shape first (plan 3.10): 1 to 32 entries, every one an object. Only then is
    // each entry checked, in input order.
    const raw = body.transfers;
    if (!Array.isArray(raw)) throw invalid('transfers must be an array');
    if (raw.length < 1 || raw.length > MAX_TRANSFERS) throw invalid(`transfers holds 1 to ${MAX_TRANSFERS} entries`);
    const entries = raw.map((entry, i) => {
      if (!isObject(entry)) throw invalid(`transfers[${i}] must be an object`);
      return entry;
    });
    const transfers = entries.map((entry, i) => readTransfer(st, entry, i));

    // Net position per wallet: every wallet's available funds must cover its net debit (D53),
    // and its total must stay at or below 2^53.
    const net = new Map<User, number>();
    for (const t of transfers) {
      net.set(t.from, (net.get(t.from) ?? 0) - t.amount);
      net.set(t.to, (net.get(t.to) ?? 0) + t.amount);
    }
    const now = clock(st);
    for (const [user, change] of net) {
      if (availableOf(st, user, now.ms) + change < 0) {
        throw conflict('insufficient_funds', `${user.handle} cannot cover the settlement`);
      }
    }
    for (const [user, change] of net) {
      if (change > 0 && user.balance > MAX_BALANCE - change) {
        throw invalid(`the settlement would take ${user.handle} above 2^53`);
      }
    }

    const committedAt = now.ts;
    const id = newId('st', (sid) => st.settlements.has(sid));
    const payments = transfers.map((t) => recordPayment(st, { ...t, settlementId: id, createdAt: committedAt }));
    for (const [user, change] of net) user.balance += change;
    st.settlements.set(id, {
      id, operatorId: caller.id, committedAt, paymentIds: payments.map((p) => p.id), seq: nextSeq(st),
    });
    return { settlement_id: id, committed_at: committedAt, payments: payments.map((p) => paymentView(st, p)) };
  });
}
