// Authorizations and captures (stage-2 "Authorizations and captures" and "API", plan 3.5, 3.10).
//
// A hold moves no money: it only lowers the payer's `available`. A capture moves money from
// the payer's held funds to the receiver. Expiry needs no timer: every operation judges it
// by the service clock it took at its start (plan 3.7, 3.13).

import { authenticate, readJson, type Ctx, type Result } from '../context.ts';
import { ApiError, conflict, forbidden, invalid, malformed, notFound } from '../errors.ts';
import { optionalNote, optionalVisibility, paging, requireAmount, requireHandle } from '../fields.ts';
import { idempotencyKey, idempotent } from '../idempotency.ts';
import { has } from '../json.ts';
import { canCredit, commitTransfer } from '../ledger.ts';
import {
  addAuthorization, AUTHORIZATION_STATUSES, availableOf, clock, closeAuthorization, formatTs, newId, nextSeq,
  statusAt, store,
  type Authorization, type State,
} from '../state.ts';
import { MAX_TS_MS } from '../time.ts';
import { authorizationView, newestFirst, paymentView } from '../views.ts';

// POST /authorizations: the caller is the payer. Exactly the precedence of POST /payments,
// with funds judged on `available` and no 2^53 guard (a hold moves no money).
export function createAuthorization(ctx: Ctx): Result {
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
    if (to.id === caller.id) throw new ApiError(422, 'self_payment', 'you cannot authorize a payment to yourself');
    const now = clock(st);
    if (availableOf(st, caller, now.ms) < amount) {
      throw conflict('insufficient_funds', 'your available balance is below the amount');
    }
    const expiresMs = Math.min(now.ms + st.authorizationTtl * 1000, MAX_TS_MS);
    const authorization: Authorization = {
      id: newId('a', (id) => st.authorizationsById.has(id)),
      fromUserId: caller.id,
      toUserId: to.id,
      amount,
      capturedAmount: 0,
      note,
      visibility,
      status: 'open',
      expiresAt: formatTs(expiresMs),
      expiresMs,
      paymentId: null,
      paymentIds: [],
      createdAt: now.ts,
      closedAt: null,
      seq: nextSeq(st),
    };
    addAuthorization(st, authorization);
    return authorizationView(st, authorization, now.ms);
  });
}

function findAuthorization(st: State, id: string): Authorization {
  const authorization = st.authorizationsById.get(id);
  if (!authorization) throw notFound('no such authorization');
  return authorization;
}

// POST /authorizations/{id}/capture: only the receiver. Precedence D50: `final` type,
// `amount` value, unknown, permission, expired, not open, above the remainder, 2^53 guard.
export function captureAuthorization(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st) => {
    if (has(body, 'final') && typeof body.final !== 'boolean') throw malformed('final must be true or false');
    const final = has(body, 'final') ? body.final === true : true;
    let amount: number | null = null;
    if (has(body, 'amount')) {
      const value = body.amount;
      if (typeof value !== 'number' || !Number.isInteger(value) || value < 1) {
        throw invalid('amount must be an integer of at least 1');
      }
      amount = value;
    }
    const authorization = findAuthorization(st, ctx.params.id);
    if (authorization.toUserId !== caller.id) throw forbidden('only the receiver may capture this authorization');
    const now = clock(st);
    const status = statusAt(authorization, now.ms);
    if (status === 'expired') throw conflict('authorization_expired', 'the authorization has expired');
    if (status !== 'open') throw conflict('authorization_not_open', `the authorization is ${status}`);
    const remaining = authorization.amount - authorization.capturedAmount;
    const take = amount ?? remaining;
    if (take > remaining) {
      throw new ApiError(422, 'capture_exceeds_authorization', `at most ${remaining} remains to capture`);
    }
    if (!canCredit(caller, take)) throw invalid('the capture would take the receiver above 2^53');
    // The payer's total and held both fall by `take`: it was reserved, so `available` is unchanged.
    const payment = commitTransfer(st, {
      from: st.users.get(authorization.fromUserId)!, to: caller, amount: take,
      note: authorization.note, visibility: authorization.visibility,
      requestId: null, settlementId: null, authorizationId: authorization.id, createdAt: now.ts,
    });
    authorization.capturedAmount += take;
    authorization.paymentIds.push(payment.id);
    authorization.paymentId = payment.id;
    if (final || authorization.capturedAmount === authorization.amount) {
      closeAuthorization(st, authorization, 'captured', now.ts);
    }
    return paymentView(st, payment);
  });
}

// POST /authorizations/{id}/void: only the payer; no key, the body is never read. Voiding a
// voided authorization is 200 with its current state; captured or expired is 409.
export function voidAuthorization(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const st = store.state;
  const authorization = findAuthorization(st, ctx.params.id);
  if (authorization.fromUserId !== caller.id) throw forbidden('only the payer may void this authorization');
  const now = clock(st);
  const status = statusAt(authorization, now.ms);
  if (status === 'open') closeAuthorization(st, authorization, 'voided', now.ts);
  else if (status !== 'voided') throw conflict('authorization_not_open', `the authorization is ${status}`);
  return { status: 200, body: authorizationView(st, authorization, now.ms) };
}

// GET /authorizations: those where the caller is payer or receiver, newest first, with the
// status judged at the read's clock (an open one past its deadline is `expired`).
export function listAuthorizations(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const { limit, offset } = paging(ctx.query);
  const direction = ctx.query.get('direction');
  if (direction !== null && direction !== 'incoming' && direction !== 'outgoing') {
    throw invalid('direction must be incoming or outgoing');
  }
  const status = ctx.query.get('status');
  if (status !== null && !AUTHORIZATION_STATUSES.includes(status)) {
    throw invalid('status must be open, captured, voided or expired');
  }
  const st = store.state;
  const now = clock(st);
  const { page, hasMore } = newestFirst(st.authorizations, (a) => {
    const incoming = a.toUserId === caller.id;
    const outgoing = a.fromUserId === caller.id;
    if (direction === 'incoming' ? !incoming : direction === 'outgoing' ? !outgoing : !incoming && !outgoing) return false;
    return status === null || statusAt(a, now.ms) === status;
  }, limit, offset);
  return {
    status: 200,
    body: { authorizations: page.map((a) => authorizationView(st, a, now.ms)), has_more: hasMore },
  };
}
