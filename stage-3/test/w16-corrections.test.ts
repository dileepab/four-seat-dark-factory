// W16: POST /payments/{id}/corrections and GET /payments/{id}/revisions.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import { Client, expectError, fixture, login, request, reset, type Server, startServer } from './helpers.ts';

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
const TS_RE = /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/;
const REVISION_FIELDS = ['amount', 'effective_at', 'payment_id', 'reason', 'recorded_at', 'revision'];
const microBefore = (ts: string) => new Date(Date.parse(ts) - 1).toISOString().replace('Z', '999Z');
const correct = (c: Client, id: string, json: unknown, k = key()) => c.post(`/payments/${id}/corrections`, { json, key: k });
const pay = async (from: Client, to: string, amount: number) => {
  const reply = await from.post('/payments', { json: { to_handle: to, amount }, key: key() });
  assert.equal(reply.status, 201, reply.text);
  return reply.body;
};
const totals = async () => Promise.all([ada, bob, cy].map(async (c) => (await c.get('/me')).body.total));
const revisions = async (c: Client, id: string) => (await c.get(`/payments/${id}/revisions`)).body.revisions;

describe('a correction (W16.1, W16.7, W16.10)', () => {
  it('appends a revision, moves the difference and keeps the original payment', async () => {
    const k = key();
    const original = await ada.post('/payments', { json: { to_handle: 'bob', amount: 1_000, note: 'rent' }, key: k });
    const p = original.body;
    const effective = p.created_at.replace('+00:00', 'Z').replace('T', 't');
    const up = await correct(ada, p.payment_id, { expected_revision: 1, amount: 1_500, effective_at: effective, reason: 'more' });
    assert.equal(up.status, 201, up.text);
    assert.deepEqual(Object.keys(up.body).sort(), REVISION_FIELDS);
    assert.deepEqual([up.body.payment_id, up.body.revision, up.body.amount, up.body.effective_at, up.body.reason],
      [p.payment_id, 2, 1_500, effective, 'more']);
    assert.match(up.body.recorded_at, TS_RE);
    assert.ok(up.body.recorded_at > p.created_at);
    assert.deepEqual(await totals(), [8_500, 4_000, 500]);

    const down = await correct(ada, p.payment_id, { expected_revision: 2, amount: 0, effective_at: effective, reason: 'refund all' });
    assert.equal(down.status, 201, down.text);
    assert.deepEqual(await totals(), [10_000, 2_500, 500], 'amount 0 reverses the payment');
    // Still one statement entry, with the new revision's zero (critic B4).
    const zero = (await ada.get('/statement')).body.entries;
    assert.deepEqual(zero.map((e: any) => [e.payment.payment_id, e.payment.amount, e.delta, e.revision, e.balance_after]),
      [[p.payment_id, 0, 0, 3, 10_000]]);
    const moved = await correct(ada, p.payment_id, { expected_revision: 3, amount: 0, effective_at: '2020-01-01T00:00:00Z', reason: 'when' });
    assert.equal(moved.status, 201, moved.text);
    assert.deepEqual(await totals(), [10_000, 2_500, 500], 'an unchanged amount moves nothing now');

    const list = await revisions(ada, p.payment_id);
    assert.deepEqual(list, await revisions(bob, p.payment_id));
    assert.deepEqual(list[0], { payment_id: p.payment_id, revision: 1, amount: 1_000, effective_at: p.created_at, recorded_at: p.created_at, reason: '' });
    assert.deepEqual(list.slice(1), [up.body, down.body, moved.body]);
    for (let i = 1; i < list.length; i++) assert.ok(list[i].recorded_at > list[i - 1].recorded_at, 'recorded times strictly increase');

    // The original stays: the feed, the replay of the original 201.
    const [feedItem] = (await bob.get('/activity')).body.payments;
    assert.deepEqual(feedItem, p);
    const replay = await ada.post('/payments', { json: { to_handle: 'bob', amount: 1_000, note: 'rent' }, key: k });
    assert.deepEqual([replay.status, replay.body], [200, p]);
  });

  it('records two corrections in one millisecond at strictly increasing times', async () => {
    const p = await pay(ada, 'bob', 100);
    const sent = await Promise.all([1, 2].map((n) => correct(ada, p.payment_id, {
      expected_revision: 1, amount: 100 + n, effective_at: p.created_at, reason: `r${n}`,
    })));
    assert.deepEqual(sent.map((r) => r.status).sort(), [201, 409]);
    const again = await correct(ada, p.payment_id, { expected_revision: 2, amount: 50, effective_at: p.created_at, reason: 'r3' });
    const list = await revisions(ada, p.payment_id);
    assert.equal(list.length, 3);
    assert.equal(list[2].recorded_at, again.body.recorded_at);
    assert.ok(list[1].recorded_at > list[0].recorded_at && list[2].recorded_at > list[1].recorded_at);
  });

  it('shows the revisions to the two parties only', async () => {
    const p = await pay(ada, 'bob', 100);
    expectError(await cy.get(`/payments/${p.payment_id}/revisions`), 404, 'not_found');
    expectError(await ada.get('/payments/p_missing/revisions'), 404, 'not_found');
    expectError(await request(port, 'GET', `/payments/${p.payment_id}/revisions`), 401, 'unauthenticated');
    assert.equal((await bob.get(`/payments/${p.payment_id}/revisions`)).status, 200);
  });
});

describe('correction idempotency (W16.2)', () => {
  it('replays, refuses reuse, claims nothing on failure and scopes keys by path', async () => {
    const p = await pay(ada, 'bob', 100);
    const q = await pay(ada, 'bob', 200);
    const body = { expected_revision: 1, amount: 150, effective_at: p.created_at, reason: 'fix' };
    expectError(await ada.post(`/payments/${p.payment_id}/corrections`, { json: body }), 400, 'missing_idempotency_key');
    expectError(await ada.post(`/payments/${p.payment_id}/corrections`, { json: body, key: '' }), 400, 'missing_idempotency_key');
    expectError(await ada.post(`/payments/${p.payment_id}/corrections`, { json: body, key: 'k'.repeat(256) }), 422, 'validation_failed');
    expectError(await ada.post(`/payments/${p.payment_id}/corrections`, { raw: '{bad', key: 'k'.repeat(256) }), 422, 'validation_failed');
    const k = key();
    const stale = await correct(ada, p.payment_id, { ...body, expected_revision: 2 }, k);
    expectError(stale, 409, 'stale_revision');
    const first = await correct(ada, p.payment_id, body, k);
    assert.equal(first.status, 201, 'the failed call claimed nothing');
    await correct(ada, p.payment_id, { ...body, expected_revision: 2, amount: 120 });
    const replay = await correct(ada, p.payment_id, body, k);
    assert.deepEqual([replay.status, replay.body], [200, first.body], 'the original revision, after newer ones');
    expectError(await correct(ada, p.payment_id, { ...body, reason: 'other' }, k), 409, 'idempotency_key_reuse');
    const elsewhere = await correct(ada, q.payment_id, { ...body, effective_at: q.created_at }, k);
    assert.equal(elsewhere.status, 201, 'the same key on another payment');
    assert.deepEqual(await totals(), [10_000 - 120 - 150, 2_500 + 120 + 150, 500]);
  });
});

describe('correction validation and permissions (W16.3, W16.4)', () => {
  it('answers 422 for every field rule, before the payment is looked up', async () => {
    const p = await pay(ada, 'bob', 100);
    const good = { expected_revision: 1, amount: 150, effective_at: p.created_at, reason: 'fix' };
    const variants: Record<string, unknown>[] = [];
    for (const name of Object.keys(good)) {
      const without = { ...good } as Record<string, unknown>;
      delete without[name];
      variants.push(without, { ...good, [name]: null });
    }
    for (const v of [true, '1', 1.5, -1, 0, 2 ** 53 + 2, [1], {}]) variants.push({ ...good, expected_revision: v });
    for (const v of [1_000_000_001, -1, 1.5, '150', false, [150]]) variants.push({ ...good, amount: v });
    const late = new Date(Date.now() + 1_000).toISOString();
    for (const v of [5, '', '2020-01-01', '2020-01-01T00:00:00', '2020-02-30T00:00:00Z', late, '9999-01-01T00:00:00Z', true]) {
      variants.push({ ...good, effective_at: v });
    }
    for (const v of ['', '\u{1F600}'.repeat(201), 5, true, ['x']]) variants.push({ ...good, reason: v });
    for (const v of variants) {
      expectError(await correct(ada, p.payment_id, v), 422, 'validation_failed');
      expectError(await correct(ada, 'p_missing', v), 422, 'validation_failed');
      expectError(await correct(bob, p.payment_id, v), 422, 'validation_failed');
    }
    assert.equal((await revisions(ada, p.payment_id)).length, 1);
    expectError(await ada.post(`/payments/${p.payment_id}/corrections`, { raw: '{bad', key: key() }), 400, 'malformed_request');
    expectError(await ada.post(`/payments/${p.payment_id}/corrections`, { raw: '[]', key: key() }), 400, 'malformed_request');
    expectError(await request(port, 'POST', `/payments/${p.payment_id}/corrections`, { json: good, key: key() }), 401, 'unauthenticated');
    expectError(await correct(ada, 'p_missing', good), 404, 'not_found');
    expectError(await correct(bob, p.payment_id, good), 403, 'forbidden');
    expectError(await correct(cy, p.payment_id, good), 403, 'forbidden');
  });

  it('accepts integral numbers written as 1.0 and 1e3, and 200 code points of reason', async () => {
    const p = await pay(ada, 'bob', 100);
    const raw = `{"expected_revision": 1.0, "amount": 1e3, "effective_at": "${p.created_at}", "reason": "${'\u{1F600}'.repeat(200)}"}`;
    const reply = await ada.post(`/payments/${p.payment_id}/corrections`, { raw, key: key() });
    assert.equal(reply.status, 201, reply.text);
    assert.deepEqual([reply.body.revision, reply.body.amount], [2, 1_000]);
  });
});

describe('linked payments and stale revisions (W16.5, W16.6)', () => {
  it('refuses captures and settlement members, seeded ones included', async () => {
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 300 }, key: key() })).body;
    const capture = (await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: { amount: 100, final: false }, key: key() })).body;
    const settled = (await ada.post('/settlements', { json: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 5 }] }, key: key() })).body;
    const body = (p: any) => ({ expected_revision: 9, amount: 1, effective_at: p.created_at, reason: 'x' });
    expectError(await correct(ada, capture.payment_id, body(capture)), 422, 'linked_payment_immutable');
    expectError(await correct(bob, capture.payment_id, body(capture)), 403, 'forbidden');
    expectError(await correct(ada, settled.payments[0].payment_id, body(settled.payments[0])), 422, 'linked_payment_immutable');
    await reset(port, fixture({
      payments: [
        { id: 'p_cap', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5, authorization_id: 'a_gone' },
        { id: 'p_set', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5, settlement_id: 's_gone' },
        { id: 'p_free', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5 },
      ],
    }));
    const seededAda = await login(port, 'ada');
    const now = new Date().toISOString();
    for (const id of ['p_cap', 'p_set']) {
      expectError(await correct(seededAda, id, { expected_revision: 1, amount: 1, effective_at: now, reason: 'x' }), 422, 'linked_payment_immutable');
    }
    assert.equal((await correct(seededAda, 'p_free', { expected_revision: 1, amount: 1, effective_at: now, reason: 'x' })).status, 201);
  });

  it('is stale unless expected_revision is the latest, and of 50 racing corrections exactly one wins', async () => {
    const p = await pay(ada, 'bob', 100);
    const body = { expected_revision: 1, amount: 110, effective_at: p.created_at, reason: 'r' };
    expectError(await correct(ada, p.payment_id, { ...body, expected_revision: 2 }), 409, 'stale_revision');
    const replies = await Promise.all(Array.from({ length: 50 }, (_, i) => correct(ada, p.payment_id, { ...body, amount: 101 + i })));
    const won = replies.filter((r) => r.status === 201);
    assert.equal(won.length, 1);
    for (const r of replies) if (r.status !== 201) expectError(r, 409, 'stale_revision');
    const amount = won[0].body.amount;
    assert.deepEqual(await totals(), [10_000 - amount, 2_500 + amount, 500], 'money moved once');
    expectError(await correct(ada, p.payment_id, body), 409, 'stale_revision');
    assert.equal((await revisions(ada, p.payment_id)).length, 2);
  });
});

describe('funds and history (W16.8)', () => {
  it('is insufficient_funds when the debit exceeds the debited wallet\'s available, holds counted', async () => {
    const p = await pay(cy, 'bob', 100);
    await cy.post('/authorizations', { json: { to_handle: 'bob', amount: 350 }, key: key() }); // cy: total 400, available 50
    const before = await totals();
    const k = key();
    expectError(await correct(cy, p.payment_id, { expected_revision: 1, amount: 151, effective_at: p.created_at, reason: 'up' }, k), 409, 'insufficient_funds');
    assert.deepEqual(await totals(), before);
    assert.equal((await revisions(cy, p.payment_id)).length, 1);
    const ok = await correct(cy, p.payment_id, { expected_revision: 1, amount: 150, effective_at: p.created_at, reason: 'up' }, k);
    assert.equal(ok.status, 201, 'the refused call claimed no key');

    // A fall debits the receiver: bob spends everything first.
    const q = await pay(ada, 'bob', 400);
    await pay(bob, 'ada', (await bob.get('/me')).body.available);
    expectError(await correct(ada, q.payment_id, { expected_revision: 1, amount: 0, effective_at: q.created_at, reason: 'down' }), 409, 'insufficient_funds');
  });

  it('is historical_overdraft when the sender did not yet have the money at the new effective_at', async () => {
    const funded = await pay(ada, 'cy', 1_000); // cy 1500
    const spend = await pay(cy, 'bob', 1_200); // cy 300
    const before = await totals();
    const earlier = { expected_revision: 1, amount: 1_200, effective_at: microBefore(funded.created_at), reason: 'earlier' };
    const k = key();
    expectError(await correct(cy, spend.payment_id, earlier, k), 409, 'historical_overdraft');
    assert.deepEqual(await totals(), before);
    const statement = (await cy.get('/statement')).body;
    assert.deepEqual(statement.entries.map((e: any) => [e.revision, e.delta]), [[1, 1_000], [1, -1_200]]);
    // At exactly the funding instant the two movements combine: 500 + 1000 - 1200 >= 0.
    const same = await correct(cy, spend.payment_id, { ...earlier, effective_at: funded.created_at }, k);
    assert.equal(same.status, 201, same.text);
    assert.deepEqual(await totals(), before);
  });

  it('combines every movement of one instant before checking, whatever their order', async () => {
    // Seeded at one instant, the spend listed before the funding: 500 - 1200 + 1000 = 300.
    const X = '2020-01-01T00:00:00Z';
    await reset(port, fixture({
      users: [
        { id: 'u_ada', email: 'ada@example.com', password: 'correct horse', display_name: 'Ada', handle: 'ada', balance: 9_000 },
        { id: 'u_bob', email: 'bob@example.com', password: 'correct horse', display_name: 'Bob', handle: 'bob', balance: 3_700 },
        { id: 'u_cy', email: 'cy@example.com', password: 'correct horse', display_name: 'Cy', handle: 'cy', balance: 300 },
      ],
      payments: [
        { id: 'p_spend', from_user_id: 'u_cy', to_user_id: 'u_bob', amount: 1_200, created_at: X },
        { id: 'p_fund', from_user_id: 'u_ada', to_user_id: 'u_cy', amount: 1_000, created_at: X },
      ],
    }));
    const [seededAda, seededCy] = await Promise.all(['ada', 'cy'].map((h) => login(port, h)));
    assert.equal((await seededCy.get('/me?as_of=2020-01-01T00:00:00Z')).body.total, 300);
    const p = await pay(seededAda, 'cy', 1);
    const fixed = await correct(seededAda, p.payment_id, { expected_revision: 1, amount: 2, effective_at: p.created_at, reason: 'one more' });
    assert.equal(fixed.status, 201, fixed.text);
  });

  it('is historical_overdraft when the receiver had spent the money before the new effective_at', async () => {
    const p = await pay(ada, 'bob', 1_000); // bob 3500
    await pay(bob, 'cy', 3_500); // bob 0
    const later = await pay(cy, 'ada', 1);
    expectError(await correct(ada, p.payment_id, { expected_revision: 1, amount: 1_000, effective_at: later.created_at, reason: 'later' }), 409, 'historical_overdraft');
    assert.deepEqual(await totals(), [9_001, 0, 3_999]);
    // A rise is affordable now and keeps every past instant covered.
    assert.equal((await correct(ada, p.payment_id, { expected_revision: 1, amount: 1_100, effective_at: p.created_at, reason: 'up' })).status, 201);
  });

  it('is historical_overdraft when a past hold would leave available negative', async () => {
    const p = await pay(ada, 'cy', 1_000); // cy 1500
    const hold = (await cy.post('/authorizations', { json: { to_handle: 'bob', amount: 1_400 }, key: key() })).body;
    await cy.post(`/authorizations/${hold.authorization_id}/void`);
    const later = await pay(bob, 'ada', 1);
    // Moved after the hold's creation: cy's total stays 500 >= 0, but 1400 was held.
    const moved = { expected_revision: 1, amount: 1_000, effective_at: later.created_at, reason: 'later' };
    expectError(await correct(ada, p.payment_id, moved), 409, 'historical_overdraft');
    assert.equal((await correct(ada, p.payment_id, { ...moved, effective_at: hold.created_at })).status, 201, 'at the hold\'s instant the payment covers it');
  });
});

describe('history reads after a correction (W16.9)', () => {
  it('selects revisions by known_at and effective time, in /me and statements and not in old snapshots', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const old = (await ada.get('/statement')).body;
    const window = { from: p.created_at, to: '9999-01-01T00:00:00Z' };
    const oldWindow = (await ada.get(`/statement?from=${encodeURIComponent(window.from)}&to=${window.to}`)).body;
    const fix = (await correct(ada, p.payment_id, { expected_revision: 1, amount: 400, effective_at: '2020-01-01T00:00:00Z', reason: 'backdated' })).body;
    const me = async (params: string) => (await ada.get(`/me?${params}`)).body.total;
    assert.equal(await me(''), 9_600);
    assert.equal(await me(`known_at=${encodeURIComponent(microBefore(fix.recorded_at))}`), 9_000, 'the previous revision');
    assert.equal(await me(`known_at=${encodeURIComponent(fix.recorded_at)}`), 9_600);
    assert.equal(await me('as_of=2019-12-31T23:59:59.999999Z'), 10_000);
    assert.equal(await me('as_of=2020-01-01T00:00:00Z'), 9_600);

    const now = (await ada.get('/statement')).body;
    assert.deepEqual(now.entries.length, 1, 'never beside the revision it replaces');
    const [entry] = now.entries;
    assert.deepEqual([entry.payment.amount, entry.delta, entry.revision, entry.effective_at, entry.recorded_at, entry.balance_after],
      [400, -400, 2, '2020-01-01T00:00:00Z', fix.recorded_at, 9_600]);
    assert.equal(entry.payment.created_at, p.created_at);
    const moved = (await ada.get(`/statement?from=${encodeURIComponent(window.from)}&to=${window.to}`)).body;
    assert.deepEqual([moved.entries, moved.opening_balance, moved.closing_balance], [[], 9_600, 9_600], 'moved out of the window');
    const known = (await ada.get(`/statement?known_at=${encodeURIComponent(microBefore(fix.recorded_at))}`)).body;
    assert.deepEqual(known.entries.map((e: any) => [e.revision, e.payment.amount]), [[1, 1_000]]);

    assert.deepEqual((await ada.get(`/statement?snapshot=${old.snapshot}`)).body, old);
    assert.deepEqual((await ada.get(`/statement?snapshot=${oldWindow.snapshot}`)).body, oldWindow);
    assert.equal(old.entries[0].payment.amount, 1_000);
    assert.deepEqual((await ada.get('/activity')).body.payments[0], p, 'the feed keeps the original');
  });
});
