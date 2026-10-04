// W19: POST /payments/{id}/refunds, refund_of on every payment, corrections bounded by refunds.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import { Client, expectError, fixture, login, request, reset, type Server, startServer, user } from './helpers.ts';

let server: Server;
let port: number;
let ada: Client;
let bob: Client;
let cy: Client;

before(async () => {
  server = await startServer();
  port = server.port;
});
after(() => server.close());
beforeEach(async () => {
  await reset(port, fixture({ settlement_operator_ids: ['u_ada'] }));
  [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
});

const key = () => randomUUID();
const PAYMENT_FIELDS = [
  'amount', 'authorization_id', 'created_at', 'currency', 'from_handle', 'from_user_id', 'note', 'payment_id',
  'refund_of', 'request_id', 'settlement_id', 'to_handle', 'to_user_id', 'visibility',
];
const microBefore = (ts: string) => new Date(Date.parse(ts) - 1).toISOString().replace('Z', '999Z');
const refund = (c: Client, id: string, amount: unknown, k = key()) => c.post(`/payments/${id}/refunds`, { json: { amount }, key: k });
const correct = (c: Client, id: string, json: unknown, k = key()) => c.post(`/payments/${id}/corrections`, { json, key: k });
const pay = async (from: Client, to: string, amount: number, extra: Record<string, unknown> = {}) => {
  const reply = await from.post('/payments', { json: { to_handle: to, amount, ...extra }, key: key() });
  assert.equal(reply.status, 201, reply.text);
  return reply.body;
};
const refunded = async (c: Client, id: string, amount: number, k = key()) => {
  const reply = await refund(c, id, amount, k);
  assert.equal(reply.status, 201, reply.text);
  return reply.body;
};
const totals = async () => Promise.all([ada, bob, cy].map(async (c) => (await c.get('/me')).body.total));
const me = async (c: Client, params: Record<string, string>) => {
  const reply = await c.get(`/me?${new URLSearchParams(params)}`);
  assert.equal(reply.status, 200, reply.text);
  return reply.body;
};

describe('a refund (W19.1)', () => {
  it('is a new payment back to the sender, linked to its target, with the target\'s note and visibility', async () => {
    const p = await pay(ada, 'bob', 1_000, { note: 'rent 😀', visibility: 'private' });
    const r = await refunded(bob, p.payment_id, 200);
    assert.deepEqual(Object.keys(r).sort(), PAYMENT_FIELDS);
    assert.deepEqual(
      [r.from_user_id, r.from_handle, r.to_user_id, r.to_handle, r.amount, r.currency, r.note, r.visibility],
      ['u_bob', 'bob', 'u_ada', 'ada', 200, 'EUR', 'rent 😀', 'private'],
    );
    assert.deepEqual([r.refund_of, r.request_id, r.authorization_id, r.settlement_id], [p.payment_id, null, null, null]);
    assert.match(r.payment_id, /^p_/);
    assert.notEqual(r.payment_id, p.payment_id);
    assert.ok(r.created_at > p.created_at, 'later than every earlier timestamp');
    assert.deepEqual(await totals(), [9_200, 3_300, 500]);

    // The feed: both parties see it, a third party does not see a private one.
    assert.deepEqual((await ada.get('/activity')).body.payments, [r, p]);
    assert.deepEqual((await bob.get('/activity')).body.payments, [r, p]);
    assert.deepEqual((await cy.get('/activity')).body.payments, []);
    const open = await pay(ada, 'bob', 100, { note: 'tip' });
    const back = await refunded(bob, open.payment_id, 100);
    assert.deepEqual([back.visibility, back.note], ['public', 'tip']);
    assert.deepEqual((await cy.get('/activity')).body.payments, [back, open]);
  });

  it('replays, refuses reuse, claims nothing on failure and scopes keys by user and path', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const path = `/payments/${p.payment_id}/refunds`;
    expectError(await bob.post(path, { json: { amount: 1 } }), 400, 'missing_idempotency_key');
    expectError(await bob.post(path, { json: { amount: 1 }, key: '' }), 400, 'missing_idempotency_key');
    expectError(await bob.post(path, { json: { amount: 1 }, key: 'k'.repeat(256) }), 422, 'validation_failed');
    expectError(await request(port, 'POST', path, { json: { amount: 1 }, key: key() }), 401, 'unauthenticated');

    const k = key();
    const first = await refunded(bob, p.payment_id, 100, k);
    await refunded(bob, p.payment_id, 50);
    assert.equal((await correct(ada, p.payment_id, { expected_revision: 1, amount: 800, effective_at: p.created_at, reason: 'less' })).status, 201);
    const replay = await refund(bob, p.payment_id, 100, k);
    assert.deepEqual([replay.status, replay.body], [200, first], 'the original body, after later refunds and corrections');
    expectError(await refund(bob, p.payment_id, 101, k), 409, 'idempotency_key_reuse');
    expectError(await bob.post(path, { json: { amount: 100, note: 'x' }, key: k }), 409, 'idempotency_key_reuse');
    expectError(await bob.post(path, { json: { amount: 'bad' }, key: k }), 409, 'idempotency_key_reuse');
    assert.deepEqual(await totals(), [9_350, 3_150, 500], 'replays move nothing');

    // A refused refund claims nothing: the same key then works with a valid body.
    const failed = key();
    expectError(await refund(bob, p.payment_id, 651, failed), 422, 'refund_exceeds_payment');
    expectError(await refund(bob, p.payment_id, 0, failed), 422, 'validation_failed');
    const later = await refunded(bob, p.payment_id, 650, failed);
    assert.equal(later.amount, 650);

    // The same key on another payment's path, and by another user, is a first use.
    const q = await pay(ada, 'bob', 10);
    assert.equal((await refund(bob, q.payment_id, 100, k)).status, 422, 'a different path: not a replay');
    assert.equal((await refund(bob, q.payment_id, 10, k)).status, 201);
    const toAda = await pay(bob, 'ada', 30);
    assert.equal((await refund(ada, toAda.payment_id, 100, k)).status, 422, 'another user: not a replay');
    assert.equal((await refund(ada, toAda.payment_id, 30, k)).status, 201);
    const sameKeyPayment = await bob.post('/payments', { json: { to_handle: 'cy', amount: 1 }, key: k });
    assert.equal(sameKeyPayment.status, 201, 'the key is scoped by path');
  });
});

describe('refund precedence (W19.2)', () => {
  it('answers 422 for an invalid amount before looking up the payment; 1.0 and 1e3 are integral', async () => {
    const p = await pay(ada, 'bob', 2_000);
    for (const id of [p.payment_id, 'p_none']) {
      for (const body of [{}, { amount: null }, { amount: true }, { amount: '5' }, { amount: 1.5 }, { amount: 0 }, { amount: -1 }, { amount: 1_000_000_001 }, { amount: [5] }]) {
        expectError(await bob.post(`/payments/${id}/refunds`, { json: body, key: key() }), 422, 'validation_failed');
      }
    }
    expectError(await bob.post(`/payments/${p.payment_id}/refunds`, { raw: '{"amount": 5', key: key() }), 400, 'malformed_request');
    expectError(await bob.post(`/payments/${p.payment_id}/refunds`, { raw: '[5]', key: key() }), 400, 'malformed_request');
    for (const raw of ['{"amount": 1.0}', '{"amount": 1e3, "extra": "ignored"}']) {
      assert.equal((await bob.post(`/payments/${p.payment_id}/refunds`, { raw, key: key() })).status, 201, raw);
    }
    assert.deepEqual(await totals(), [9_001, 3_499, 500]);
  });

  it('is 404, then 403 for anyone but the receiver, then invalid_refund_target, then the cap, then the funds', async () => {
    const p = await pay(ada, 'bob', 1_000);
    expectError(await refund(bob, 'p_none', 1), 404, 'not_found');
    expectError(await refund(ada, p.payment_id, 1), 403, 'forbidden');
    expectError(await refund(cy, p.payment_id, 1), 403, 'forbidden');
    expectError(await refund(cy, 'p_none', 1), 404, 'not_found');
    const r = await refunded(bob, p.payment_id, 300);
    expectError(await refund(ada, r.payment_id, 1), 422, 'invalid_refund_target');
    expectError(await refund(ada, r.payment_id, 1_000_000), 422, 'invalid_refund_target');
    expectError(await refund(bob, r.payment_id, 1), 403, 'forbidden');
    // The cap: 700 left. One more than that is refused, exactly that is accepted.
    expectError(await refund(bob, p.payment_id, 701), 422, 'refund_exceeds_payment');
    const all = await refunded(bob, p.payment_id, 700);
    assert.equal(all.amount, 700);
    expectError(await refund(bob, p.payment_id, 1), 422, 'refund_exceeds_payment');
    assert.deepEqual(await totals(), [10_000, 2_500, 500]);

    // The cap before the funds: bob cannot afford 1 200, but the cap answers first.
    const q = await pay(ada, 'bob', 1_000);
    await pay(bob, 'cy', 3_400);
    assert.equal((await bob.get('/me')).body.available, 100);
    expectError(await refund(bob, q.payment_id, 1_200), 422, 'refund_exceeds_payment');
    expectError(await refund(bob, q.payment_id, 101), 409, 'insufficient_funds');
    assert.equal((await refund(bob, q.payment_id, 100)).status, 201);
  });

  it('judges the funds on available: held money cannot be refunded', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const hold = await bob.post('/authorizations', { json: { to_handle: 'cy', amount: 3_000 }, key: key() });
    assert.equal(hold.status, 201, hold.text);
    assert.deepEqual([(await bob.get('/me')).body.total, (await bob.get('/me')).body.available], [3_500, 500]);
    const k = key();
    expectError(await refund(bob, p.payment_id, 501, k), 409, 'insufficient_funds');
    assert.deepEqual(await totals(), [9_000, 3_500, 500], 'a refused refund changes nothing');
    assert.equal((await refund(bob, p.payment_id, 500, k)).status, 201, 'and leaves its key free');
    assert.deepEqual((await bob.get('/me')).body.available, 0);
  });

  it('refuses a refund that would take the payment\'s sender above 2^53', async () => {
    await reset(port, fixture({ users: [user('ada', 2 ** 53), user('bob', 0), user('cy', 1_000)] }));
    [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
    const p = await pay(ada, 'bob', 1_000);
    await pay(cy, 'ada', 1_000);
    const k = key();
    expectError(await refund(bob, p.payment_id, 1, k), 422, 'validation_failed');
    assert.deepEqual(await totals(), [2 ** 53, 1_000, 0]);
    await pay(ada, 'cy', 1);
    assert.equal((await refund(bob, p.payment_id, 1, k)).status, 201);
  });
});

describe('refund targets and the cap (W19.3, F41)', () => {
  it('lets the receiver refund a direct, request, capture, settlement and seeded payment', async () => {
    await reset(port, fixture({
      settlement_operator_ids: ['u_ada'],
      payments: [{ id: 'p_seed', from_user_id: 'u_cy', to_user_id: 'u_bob', amount: 400, created_at: '2020-01-01T00:00:00Z' }],
    }));
    [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
    const direct = await pay(ada, 'bob', 100);
    const ask = (await bob.post('/requests', { json: { payer_handle: 'ada', amount: 200 }, key: key() })).body;
    const viaRequest = (await ada.post(`/requests/${ask.request_id}/pay`, { json: {}, key: key() })).body;
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 300 }, key: key() })).body;
    const capture = (await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 250 }, key: key() })).body;
    const settled = (await ada.post('/settlements', { json: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 50 }] }, key: key() })).body;
    const member = settled.payments[0];
    const before = await totals();
    for (const [target, amount] of [[direct, 100], [viaRequest, 200], [capture, 250], [member, 50]] as const) {
      const r = await refunded(bob, target.payment_id, amount);
      assert.deepEqual([r.refund_of, r.from_handle, r.to_handle, r.amount], [target.payment_id, 'bob', 'ada', amount]);
      assert.deepEqual([r.request_id, r.authorization_id, r.settlement_id], [null, null, null]);
    }
    const seeded = await refunded(bob, 'p_seed', 400);
    assert.deepEqual([seeded.refund_of, seeded.to_handle], ['p_seed', 'cy']);
    assert.deepEqual(await totals(), [before[0] + 600, before[1] - 1_000, before[2] + 400]);
  });

  it('follows the current corrected amount: down to it after a correction, nothing after a correction to 0', async () => {
    const p = await pay(ada, 'bob', 1_000);
    assert.equal((await correct(ada, p.payment_id, { expected_revision: 1, amount: 600, effective_at: p.created_at, reason: 'less' })).status, 201);
    expectError(await refund(bob, p.payment_id, 601), 422, 'refund_exceeds_payment');
    await refunded(bob, p.payment_id, 600);
    const q = await pay(ada, 'bob', 500);
    assert.equal((await correct(ada, q.payment_id, { expected_revision: 1, amount: 0, effective_at: q.created_at, reason: 'void' })).status, 201);
    expectError(await refund(bob, q.payment_id, 1), 422, 'refund_exceeds_payment');
    // A correction up raises the cap; the effective time plays no part.
    assert.equal((await correct(ada, q.payment_id, { expected_revision: 2, amount: 900, effective_at: '2020-01-01T00:00:00Z', reason: 'more' })).status, 201);
    await refunded(bob, q.payment_id, 900);
    assert.deepEqual(await totals(), [10_000, 2_500, 500]);
  });
});

describe('what a refund leaves alone (W19.4, I70, I75)', () => {
  it('keeps the request paid, the authorization, the released hold, the settlement and the target', async () => {
    const ask = (await bob.post('/requests', { json: { payer_handle: 'ada', amount: 200 }, key: key() })).body;
    const payKey = key();
    const viaRequest = (await ada.post(`/requests/${ask.request_id}/pay`, { json: {}, key: payKey })).body;
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 300 }, key: key() })).body;
    const capture = (await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 100, final: false }, key: key() })).body;
    assert.equal((await ada.post(`/authorizations/${hold.authorization_id}/void`)).status, 200);
    const full = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 120 }, key: key() })).body;
    const fullCapture = (await bob.post(`/authorizations/${full.authorization_id}/capture`, { json: {}, key: key() })).body;
    const settleKey = key();
    const settleBody = { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 50 }, { from_handle: 'bob', to_handle: 'cy', amount: 20 }] };
    const settled = (await ada.post('/settlements', { json: settleBody, key: settleKey })).body;
    const views = async () => Promise.all([ada, bob, cy].map(async (c) => ({
      requests: (await c.get('/requests')).body,
      authorizations: (await c.get('/authorizations')).body,
      held: (await c.get('/me')).body.held,
      revisions: c === cy ? null : (await c.get(`/payments/${capture.payment_id}/revisions`)).body,
    })));
    const before = await views();
    const feedBefore = (await ada.get('/activity?limit=200')).body.payments;

    const refunds = [];
    for (const [target, amount] of [[viaRequest, 200], [capture, 100], [fullCapture, 120], [settled.payments[0], 50]] as const) {
      refunds.push(await refunded(bob, target.payment_id, amount));
    }
    refunds.push(await refunded(cy, settled.payments[1].payment_id, 20));
    assert.deepEqual(await views(), before, 'requests, authorizations, holds and revisions unchanged');
    const [paid] = (await ada.get('/requests')).body.requests;
    assert.deepEqual([paid.status, paid.payment_id], ['paid', viaRequest.payment_id]);
    const feedAfter = (await ada.get('/activity?limit=200')).body.payments;
    assert.deepEqual(feedAfter.slice(refunds.length), feedBefore, 'every earlier feed item unchanged');
    assert.deepEqual(feedAfter.slice(0, refunds.length), [...refunds].reverse());
    for (const r of refunds) assert.equal(r.settlement_id, null, 'a refund of a member is not a member');

    const settleReplay = await ada.post('/settlements', { json: settleBody, key: settleKey });
    assert.deepEqual([settleReplay.status, settleReplay.body], [200, settled]);
    const payReplay = await ada.post(`/requests/${ask.request_id}/pay`, { json: {}, key: payKey });
    assert.deepEqual([payReplay.status, payReplay.body], [200, viaRequest]);
    assert.deepEqual(await totals(), [10_000, 2_500, 500], 'every payment refunded in full');
  });
});

describe('a refund of a capture from a hold still open (W19.4)', () => {
  it('leaves the hold, the payer\'s held and the hold\'s history as they were', async () => {
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 500 }, key: key() })).body;
    const capture = (await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 200, final: false }, key: key() })).body;
    const later = await pay(cy, 'bob', 1);
    const instants = [hold.created_at, microBefore(capture.created_at), capture.created_at, later.created_at];
    const history = async () => Promise.all(instants.map(async (t) => {
      const body = await me(ada, { as_of: t });
      return [body.total, body.held, body.available];
    }));
    const listed = async () => (await ada.get('/authorizations')).body.authorizations;
    const [open] = await listed();
    assert.deepEqual([open.status, open.captured_amount, open.remaining_amount, open.payment_ids, open.closed_at],
      ['open', 200, 300, [capture.payment_id], null]);
    const before = { listed: await listed(), history: await history(), me: await ada.get('/me') };

    const r = await refunded(bob, capture.payment_id, 200);
    assert.deepEqual(await listed(), before.listed);
    assert.deepEqual(await history(), before.history, 'every earlier instant unchanged');
    const now = (await ada.get('/me')).body;
    assert.deepEqual([now.total, now.held, now.available],
      [before.me.body.total + 200, before.me.body.held, before.me.body.available + 200], 'held unchanged');
    assert.equal(now.held, 300);
    const at = await me(ada, { as_of: r.created_at });
    assert.deepEqual([at.total, at.held], [now.total, 300]);
    // The hold still captures its remainder normally.
    const rest = await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: {}, key: key() });
    assert.equal(rest.status, 201, rest.text);
    assert.equal(rest.body.amount, 300);
  });
});

describe('refund_of: null on every other payment (W19.5)', () => {
  it('on new, request, settlement, capture and seeded payments, in the feed, statements and replays', async () => {
    await reset(port, fixture({
      settlement_operator_ids: ['u_ada'],
      payments: [{ id: 'p_seed', from_user_id: 'u_cy', to_user_id: 'u_bob', amount: 40, refund_of: 'p_ignored', correction_batch_id: 'cb_x' }],
    }));
    [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
    const payKey = key();
    const direct = await ada.post('/payments', { json: { to_handle: 'bob', amount: 10 }, key: payKey });
    const ask = (await bob.post('/requests', { json: { payer_handle: 'ada', amount: 20 }, key: key() })).body;
    const viaRequest = (await ada.post(`/requests/${ask.request_id}/pay`, { json: {}, key: key() })).body;
    const settled = (await ada.post('/settlements', { json: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 5 }] }, key: key() })).body;
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 30 }, key: key() })).body;
    const capture = (await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: {}, key: key() })).body;
    for (const p of [direct.body, viaRequest, settled.payments[0], capture]) assert.equal(p.refund_of, null);
    const feed = (await bob.get('/activity')).body.payments;
    assert.equal(feed.length, 5);
    for (const p of feed) assert.equal(p.refund_of, null);
    assert.equal(feed.find((p: any) => p.payment_id === 'p_seed').refund_of, null, 'a fixture refund_of is ignored');
    for (const e of (await bob.get('/statement')).body.entries) assert.equal(e.payment.refund_of, null);
    const replay = await ada.post('/payments', { json: { to_handle: 'bob', amount: 10 }, key: payKey });
    assert.deepEqual([replay.status, replay.body], [200, direct.body]);
  });
});

describe('single corrections and refunds (W19.6, D94)', () => {
  it('refuses to correct a refund, before the revision check', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const r = await refunded(bob, p.payment_id, 300);
    for (const expected of [1, 9]) {
      expectError(await correct(bob, r.payment_id, { expected_revision: expected, amount: 1, effective_at: r.created_at, reason: 'x' }), 422, 'linked_payment_immutable');
    }
    expectError(await correct(ada, r.payment_id, { expected_revision: 1, amount: 1, effective_at: r.created_at, reason: 'x' }), 403, 'forbidden');
  });

  it('refuses an amount below the refunded total after stale_revision and before insufficient_funds; equal is accepted', async () => {
    const p = await pay(ada, 'bob', 1_000);
    await refunded(bob, p.payment_id, 300);
    const body = (target: any, amount: number, expected = 1) => ({ expected_revision: expected, amount, effective_at: target.created_at, reason: 'r' });
    expectError(await correct(ada, p.payment_id, body(p, 299, 2)), 409, 'stale_revision');
    expectError(await correct(ada, p.payment_id, body(p, 299)), 422, 'refund_exceeds_payment');
    expectError(await correct(ada, p.payment_id, body(p, 0)), 422, 'refund_exceeds_payment');
    const equal = await correct(ada, p.payment_id, body(p, 300));
    assert.equal(equal.status, 201, equal.text);
    assert.deepEqual(await totals(), [10_000, 2_500, 500]);
    expectError(await refund(bob, p.payment_id, 1), 422, 'refund_exceeds_payment');

    // bob cannot afford any fall of q now; the refund rule still answers first.
    const q = await pay(ada, 'bob', 1_000);
    await refunded(bob, q.payment_id, 300);
    await pay(bob, 'cy', 3_200);
    expectError(await correct(ada, q.payment_id, body(q, 100)), 422, 'refund_exceeds_payment');
    expectError(await correct(ada, q.payment_id, body(q, 300)), 409, 'insufficient_funds');
    assert.deepEqual(await totals(), [9_300, 0, 3_700]);
  });
});

describe('refunds in history (W19.7, I76, I77)', () => {
  it('is revision 1 at its created_at, a statement entry and part of every historical view from then on', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const oldAda = (await ada.get('/statement')).body;
    const oldBob = (await bob.get('/statement')).body;
    const r = await refunded(bob, p.payment_id, 200);

    const expected = [{ payment_id: r.payment_id, revision: 1, amount: 200, effective_at: r.created_at, recorded_at: r.created_at, reason: '' }];
    assert.deepEqual((await bob.get(`/payments/${r.payment_id}/revisions`)).body.revisions, expected);
    assert.deepEqual((await ada.get(`/payments/${r.payment_id}/revisions`)).body.revisions, expected);
    expectError(await cy.get(`/payments/${r.payment_id}/revisions`), 404, 'not_found');

    const bobEntries = (await bob.get('/statement')).body.entries;
    assert.deepEqual(bobEntries.map((e: any) => [e.payment.payment_id, e.payment.refund_of, e.delta, e.balance_after, e.effective_at]),
      [[p.payment_id, null, 1_000, 3_500, p.created_at], [r.payment_id, p.payment_id, -200, 3_300, r.created_at]]);
    const adaEntries = (await ada.get('/statement')).body.entries;
    assert.deepEqual(adaEntries.map((e: any) => [e.delta, e.balance_after]), [[-1_000, 9_000], [200, 9_200]]);

    assert.equal((await me(ada, { as_of: microBefore(r.created_at) })).total, 9_000);
    assert.equal((await me(ada, { as_of: r.created_at })).total, 9_200);
    assert.equal((await me(bob, { as_of: r.created_at })).available, 3_300);
    assert.equal((await me(bob, { as_of: r.created_at, known_at: microBefore(r.created_at) })).total, 3_500, 'not known yet');
    assert.equal((await me(bob, { known_at: r.created_at })).total, 3_300);

    assert.deepEqual((await ada.get(`/statement?snapshot=${oldAda.snapshot}`)).body, oldAda, 'a snapshot from before pages unchanged');
    assert.deepEqual((await bob.get(`/statement?snapshot=${oldBob.snapshot}`)).body, oldBob);
  });

  it('counts in the history check of a later correction', async () => {
    const q = await pay(cy, 'bob', 500);
    const p = await pay(ada, 'bob', 1_000);
    await refunded(bob, p.payment_id, 1_000);
    const spent = await pay(bob, 'ada', 2_900);
    const later = await pay(ada, 'cy', 1);
    // Moving q after bob's spend: bob's 2 900 would have been covered by p alone, but not after
    // the refund gave p back.
    assert.ok(spent.created_at < later.created_at);
    const moved = await correct(cy, q.payment_id, { expected_revision: 1, amount: 500, effective_at: later.created_at, reason: 'late' });
    expectError(moved, 409, 'historical_overdraft');
    assert.deepEqual(await totals(), [10_000 - 1_000 + 1_000 + 2_900 - 1, 2_500 + 500 + 1_000 - 1_000 - 2_900, 1]);
  });
});

describe('concurrent refunds (W19.8)', () => {
  it('never exceed the cap together, and money is conserved', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const replies = await Promise.all(Array.from({ length: 50 }, () => refund(bob, p.payment_id, 30)));
    const won = replies.filter((r) => r.status === 201);
    assert.equal(won.length, 33);
    for (const r of replies) if (r.status !== 201) expectError(r, 422, 'refund_exceeds_payment');
    assert.deepEqual(await totals(), [9_990, 2_510, 500]);
    assert.equal(new Set(won.map((r) => r.body.created_at)).size, 33, 'one timestamp each');
  });

  it('racing a correction that lowers the amount, never break the cap', async () => {
    for (let round = 0; round < 5; round++) {
      const p = await pay(ada, 'bob', 1_000);
      const lower = correct(ada, p.payment_id, { expected_revision: 1, amount: 500, effective_at: p.created_at, reason: 'less' });
      const replies = await Promise.all([...Array.from({ length: 20 }, () => refund(bob, p.payment_id, 60)), lower]);
      const corrected = replies[20].status === 201;
      if (!corrected) expectError(replies[20], 422, 'refund_exceeds_payment');
      const sum = replies.slice(0, 20).filter((r) => r.status === 201).reduce((n, r) => n + r.body.amount, 0);
      const revisions = (await ada.get(`/payments/${p.payment_id}/revisions`)).body.revisions;
      assert.ok(sum <= revisions.at(-1).amount, `round ${round}: ${sum} refunded of ${revisions.at(-1).amount}`);
      assert.equal(revisions.length, corrected ? 2 : 1);
    }
    const all = await totals();
    assert.equal(all.reduce((a, b) => a + b, 0), 13_000);
  });
});
