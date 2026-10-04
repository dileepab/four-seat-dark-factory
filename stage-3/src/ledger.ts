// Moving money. Callers check every rule first; these functions only commit.

import {
  addPayment, MAX_BALANCE, newId, nextSeq,
  type Payment, type State, type User, type Visibility,
} from './state.ts';

// True when crediting `amount` keeps the balance within 2^53 (D19). Written as a
// subtraction so the comparison is exact for every balance up to 2^53.
export function canCredit(user: User, amount: number): boolean {
  return user.balance <= MAX_BALANCE - amount;
}

export interface Transfer {
  from: User;
  to: User;
  amount: number;
  note: string;
  visibility: Visibility;
  requestId: string | null;
  settlementId: string | null;
  authorizationId: string | null;
  createdAt: string;
}

// Record one payment and apply its balance changes, in one synchronous step.
export function commitTransfer(st: State, t: Transfer): Payment {
  const payment = recordPayment(st, t);
  t.from.balance -= t.amount;
  t.to.balance += t.amount;
  return payment;
}

// Record the payment only; the caller applies the balance changes in the same step.
export function recordPayment(st: State, t: Transfer): Payment {
  return addPayment(st, {
    id: newId('p', (id) => st.paymentsById.has(id)),
    fromUserId: t.from.id,
    toUserId: t.to.id,
    amount: t.amount,
    note: t.note,
    visibility: t.visibility,
    requestId: t.requestId,
    settlementId: t.settlementId,
    authorizationId: t.authorizationId,
    createdAt: t.createdAt,
    seq: nextSeq(st),
  });
}
