// Payment requests (spec §4 "Payments and requests", §8 request endpoints).

import { authenticate, readJson, type Ctx, type Result } from '../context.ts';
import { ApiError, conflict, forbidden, invalid, notFound } from '../errors.ts';
import { optionalNote, optionalVisibility, paging, requireAmount, requireHandle } from '../fields.ts';
import { idempotencyKey, idempotent } from '../idempotency.ts';
import { canCredit, commitTransfer } from '../ledger.ts';
import {
  addRequest, availableOf, clock, newId, nextSeq, nextTs, REQUEST_STATUSES, store,
  type PayRequest, type RequestStatus, type State, type User,
} from '../state.ts';
import { newestFirst, paymentView, requestView } from '../views.ts';

// A new pending request from `requester` to `payer`. The payer's balance is never checked.
export function openRequest(
  st: State, requester: User, payer: User, amount: number, note: string, createdAt: string,
): PayRequest {
  const request: PayRequest = {
    id: newId('rq', (id) => st.requestsById.has(id)),
    requesterId: requester.id,
    payerId: payer.id,
    amount,
    note,
    status: 'pending',
    paymentId: null,
    createdAt,
    seq: nextSeq(st),
  };
  addRequest(st, request);
  return request;
}

export function createRequest(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st) => {
    const payerHandle = requireHandle(body, 'payer_handle');
    const amount = requireAmount(body);
    const note = optionalNote(body);
    const payer = st.usersByHandle.get(payerHandle);
    if (!payer) throw notFound('no user has that handle');
    if (payer.id === caller.id) throw new ApiError(422, 'self_request', 'you cannot request money from yourself');
    return requestView(st, openRequest(st, caller, payer, amount, note, nextTs(st)));
  });
}

function findRequest(st: State, id: string): PayRequest {
  const request = st.requestsById.get(id);
  if (!request) throw notFound('no such request');
  return request;
}

function notPending(): ApiError {
  return conflict('request_not_pending', 'the request is no longer pending');
}

// Only the payer may pay. The payment copies the request's parties, amount and note;
// the visibility is the payer's choice (D31). The request becomes paid in the same step.
export function payRequest(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const key = idempotencyKey(ctx);
  const body = readJson(ctx);
  return idempotent(ctx, caller, key, body, (st) => {
    const visibility = optionalVisibility(body);
    const request = findRequest(st, ctx.params.id);
    if (request.payerId !== caller.id) throw forbidden('only the payer may pay this request');
    if (request.status !== 'pending') throw notPending();
    const now = clock(st);
    if (availableOf(st, caller, now.ms) < request.amount) {
      throw conflict('insufficient_funds', 'your available balance is below the amount');
    }
    const requester = st.users.get(request.requesterId)!;
    if (!canCredit(requester, request.amount)) throw invalid('the payment would take the requester above 2^53');
    const payment = commitTransfer(st, {
      from: caller, to: requester, amount: request.amount, note: request.note, visibility,
      requestId: request.id, settlementId: null, authorizationId: null, createdAt: now.ts,
    });
    request.status = 'paid';
    request.paymentId = payment.id;
    return paymentView(st, payment);
  });
}

// Decline (payer) and cancel (requester): no key, the body is never read. Repeating the
// same action is 200 with the current state; any other final state is 409.
function settleRequest(ctx: Ctx, party: 'payerId' | 'requesterId', target: RequestStatus): Result {
  const caller = authenticate(ctx);
  const st = store.state;
  const request = findRequest(st, ctx.params.id);
  if (request[party] !== caller.id) {
    throw forbidden(party === 'payerId' ? 'only the payer may decline' : 'only the requester may cancel');
  }
  if (request.status === 'pending') request.status = target;
  else if (request.status !== target) throw notPending();
  return { status: 200, body: requestView(st, request) };
}

export function declineRequest(ctx: Ctx): Result {
  return settleRequest(ctx, 'payerId', 'declined');
}

export function cancelRequest(ctx: Ctx): Result {
  return settleRequest(ctx, 'requesterId', 'cancelled');
}

// Requests where the caller is a party, filtered by direction and status, newest first.
export function listRequests(ctx: Ctx): Result {
  const caller = authenticate(ctx);
  const { limit, offset } = paging(ctx.query);
  const direction = ctx.query.get('direction');
  if (direction !== null && direction !== 'incoming' && direction !== 'outgoing') {
    throw invalid('direction must be incoming or outgoing');
  }
  const status = ctx.query.get('status');
  if (status !== null && !REQUEST_STATUSES.includes(status)) {
    throw invalid('status must be pending, paid, declined or cancelled');
  }
  const st = store.state;
  const { page, hasMore } = newestFirst(st.requests, (r) => {
    const incoming = r.payerId === caller.id;
    const outgoing = r.requesterId === caller.id;
    if (direction === 'incoming' ? !incoming : direction === 'outgoing' ? !outgoing : !incoming && !outgoing) return false;
    return status === null || r.status === status;
  }, limit, offset);
  return { status: 200, body: { requests: page.map((r) => requestView(st, r)), has_more: hasMore } };
}
