// W4: atomic net settlements.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import {
  Client, expectError, fixture, login, request, reset, startServer, user,
  type Server,
} from './helpers.ts';

let server: Server;
let port: number;
let ada: Client; // the operator
let bob: Client;
let cy: Client;
let dee: Client; // starts at 0

before(async () => {
  server = await startServer();
  port = server.port;
});
after(() => server.close());
beforeEach(async () => {
  await reset(port, fixture({
    users: [user('ada', 10_000), user('bob', 2_500), user('cy', 500), user('dee', 0)],
    settlement_operator_ids: ['u_ada'],
  }));
  [ada, bob, cy, dee] = await Promise.all(['ada', 'bob', 'cy', 'dee'].map((h) => login(port, h)));
});

const key = () => randomUUID();
const balance = async (client: Client) => (await client.get('/me')).body.balance as number;
const balances = () => Promise.all([ada, bob, cy, dee].map(balance));
const settle = (client: Client, transfers: unknown, k: string = key()) =>
  client.post('/settlements', { json: { transfers }, key: k });
const t = (from: string, to: string, amount: unknown, extra: Record<string, unknown> = {}) =>
  ({ from_handle: from, to_handle: to, amount, ...extra });

describe('POST /settlements', () => {
  it('commits every transfer and returns the receipts in input order', async () => {
    const reply = await settle(ada, [t('ada', 'bob', 100), t('bob', 'cy', 50, { note: 'n', visibility: 'private' })]);
    assert.equal(reply.status, 201);
    const body = reply.body;
    assert.deepEqual(Object.keys(body).sort(), ['committed_at', 'payments', 'settlement_id']);
    assert.match(body.committed_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/);
    assert.deepEqual(body.payments.map((p: any) => [p.from_handle, p.to_handle, p.amount, p.note, p.visibility]),
      [['ada', 'bob', 100, '', 'public'], ['bob', 'cy', 50, 'n', 'private']]);
    for (const p of body.payments) {
      assert.equal(p.settlement_id, body.settlement_id);
      assert.equal(p.request_id, null);
      assert.equal(p.created_at, body.committed_at);
      assert.equal(p.currency, 'EUR');
    }
    assert.deepEqual(await balances(), [9_900, 2_550, 550, 0]);
  });

  it('judges affordability on net positions: a chain through an empty wallet succeeds', async () => {
    const reply = await settle(ada, [t('dee', 'cy', 300), t('bob', 'dee', 300)]);
    assert.equal(reply.status, 201, reply.text);
    assert.deepEqual(await balances(), [10_000, 2_200, 800, 0]);
    const both = await settle(ada, [t('cy', 'bob', 800), t('bob', 'cy', 800)]);
    assert.equal(both.status, 201);
  });

  it('refuses a batch that leaves any wallet below zero, and changes nothing', async () => {
    const k = key();
    expectError(await settle(ada, [t('ada', 'bob', 100), t('dee', 'cy', 1)], k), 409, 'insufficient_funds');
    expectError(await settle(ada, [t('cy', 'bob', 400), t('cy', 'dee', 101)]), 409, 'insufficient_funds');
    assert.deepEqual(await balances(), [10_000, 2_500, 500, 0]);
    assert.deepEqual((await ada.get('/activity')).body.payments, []);
    // The failed key claimed nothing.
    assert.equal((await settle(ada, [t('ada', 'dee', 1)], k)).status, 201);
  });

  it('applies the permission before the key and the body', async () => {
    expectError(await request(port, 'POST', '/settlements', { json: { transfers: [t('ada', 'bob', 1)] }, key: key() }),
      401, 'unauthenticated');
    expectError(await bob.post('/settlements', { raw: '{nope' }), 403, 'forbidden');
    expectError(await bob.post('/settlements', { json: { transfers: [t('bob', 'cy', 1)] }, key: key() }), 403, 'forbidden');
    expectError(await ada.post('/settlements', { json: { transfers: [t('ada', 'bob', 1)] } }), 400, 'missing_idempotency_key');
    expectError(await ada.post('/settlements', { raw: '{nope', key: key() }), 400, 'malformed_request');
  });

  it('refuses a malformed batch shape with 422', async () => {
    for (const transfers of [undefined, null, 'x', {}, [], Array.from({ length: 33 }, () => t('ada', 'bob', 1)), [5], [null], [[]]]) {
      expectError(await settle(ada, transfers), 422, 'validation_failed');
    }
    assert.equal((await settle(ada, Array.from({ length: 32 }, () => t('ada', 'bob', 1)))).status, 201);
  });

  it('applies the ordinary payment rules to each entry, all as 422', async () => {
    const bad = [
      t('ada', 'bob', 0), t('ada', 'bob', -1), t('ada', 'bob', 1.5), t('ada', 'bob', 1_000_000_001), t('ada', 'bob', '1'),
      t('ada', 'bob', null), { from_handle: 'ada', to_handle: 'bob' }, { to_handle: 'bob', amount: 1 },
      { from_handle: 'ada', amount: 1 }, t(5 as unknown as string, 'bob', 1), t('ada', null as unknown as string, 1),
      t('ada', 'bob', 1, { note: 'x'.repeat(201) }), t('ada', 'bob', 1, { note: null }),
      t('ada', 'bob', 1, { visibility: 'Public' }), t('ada', 'bob', 1, { visibility: null }),
    ];
    for (const entry of bad) expectError(await settle(ada, [entry]), 422, 'validation_failed');
    expectError(await settle(ada, [t('ada', 'ada', 1)]), 422, 'self_payment');
    expectError(await settle(ada, [t('nobody', 'bob', 1)]), 404, 'not_found');
    expectError(await settle(ada, [t('ada', 'nobody', 1)]), 404, 'not_found');
    assert.equal((await settle(ada, [t('ada', 'bob', 1, { colour: 'blue' })])).status, 201);
  });

  it('refuses a non-object entry as batch shape, before any entry is checked (plan 3.10)', async () => {
    const k = key();
    expectError(await settle(ada, [t('nobody', 'bob', 1), 7], k), 422, 'validation_failed');
    expectError(await settle(ada, [t('bob', 'bob', 1), 'x'], k), 422, 'validation_failed');
    expectError(await settle(ada, [t('ada', 'bob', 0), null]), 422, 'validation_failed');
    expectError(await settle(ada, [t('dee', 'bob', 5), [t('ada', 'bob', 1)]]), 422, 'validation_failed');
    assert.deepEqual(await balances(), [10_000, 2_500, 500, 0]);
    assert.deepEqual((await ada.get('/activity')).body.payments, []);
    assert.equal((await settle(ada, [t('ada', 'bob', 1)], k)).status, 201, 'the refused key was not claimed');
  });

  it('decides entry errors in input order, all before the funds check', async () => {
    expectError(await settle(ada, [t('nobody', 'bob', 1), t('ada', 'bob', 0)]), 404, 'not_found');
    expectError(await settle(ada, [t('ada', 'bob', 0), t('nobody', 'bob', 1)]), 422, 'validation_failed');
    expectError(await settle(ada, [t('dee', 'bob', 5), t('ada', 'ada', 1)]), 422, 'self_payment');
    expectError(await settle(ada, [t('dee', 'bob', 5), t('ada', 'ghost', 1)]), 404, 'not_found');
    // Within one entry: an unknown sender before an unknown receiver, both before self.
    expectError(await settle(ada, [t('ghost', 'ghost', 1)]), 404, 'not_found');
  });

  it('refuses to take a wallet above 2^53', async () => {
    await reset(port, fixture({
      users: [user('ada', 100), user('rich', 2 ** 53 - 10)], settlement_operator_ids: ['u_ada'],
    }));
    const a = await login(port, 'ada');
    expectError(await settle(a, [t('ada', 'rich', 11)]), 422, 'validation_failed');
    assert.equal((await settle(a, [t('ada', 'rich', 11), t('rich', 'ada', 1)])).status, 201);
  });

  it('replays the complete original with 200 and refuses a different body', async () => {
    const k = key();
    const first = await settle(ada, [t('ada', 'bob', 100), t('bob', 'cy', 100)], k);
    const replay = await settle(ada, [t('ada', 'bob', 100), t('bob', 'cy', 100)], k);
    assert.equal(replay.status, 200);
    assert.deepEqual(replay.body, first.body);
    expectError(await settle(ada, [t('bob', 'cy', 100), t('ada', 'bob', 100)], k), 409, 'idempotency_key_reuse');
    assert.deepEqual(await balances(), [9_900, 2_500, 600, 0]);
  });

  it('members follow the ordinary feed rule; other payments carry settlement_id null', async () => {
    const plain = (await bob.post('/payments', { json: { to_handle: 'cy', amount: 1 }, key: key() })).body;
    assert.equal(plain.settlement_id, null);
    const body = (await settle(ada, [t('bob', 'cy', 10, { visibility: 'private' }), t('cy', 'bob', 5)])).body;
    const [priv, pub] = body.payments;
    assert.deepEqual((await ada.get('/activity')).body.payments, [pub, plain]);
    assert.deepEqual((await bob.get('/activity')).body.payments, [pub, priv, plain]);
    assert.deepEqual((await dee.get('/activity')).body.payments, [pub, plain]);
  });

  it('gives an operator no read access to other users requests or private payments', async () => {
    await bob.post('/requests', { json: { payer_handle: 'cy', amount: 5 }, key: key() });
    await bob.post('/payments', { json: { to_handle: 'cy', amount: 5, visibility: 'private' }, key: key() });
    assert.deepEqual((await ada.get('/requests')).body.requests, []);
    assert.deepEqual((await ada.get('/activity')).body.payments, []);
    const rq = (await cy.get('/requests')).body.requests[0];
    expectError(await ada.post(`/requests/${rq.request_id}/pay`, { json: {}, key: key() }), 403, 'forbidden');
  });

  it('concurrent settlements and payments stay conserved and non-negative', async () => {
    const ops = await Promise.all(Array.from({ length: 10 }, () => login(port, 'ada')));
    const work = [
      ...ops.map((op, i) => settle(op, [t('bob', 'dee', 200 + i), t('dee', 'cy', 150), t('cy', 'bob', 100)])),
      ...Array.from({ length: 20 }, (_, i) => [bob, cy, dee][i % 3].post('/payments', {
        json: { to_handle: ['cy', 'dee', 'bob'][i % 3], amount: 120 }, key: key(),
      })),
    ];
    const replies = await Promise.all(work);
    for (const r of replies) assert.ok([201, 409].includes(r.status), r.text);
    const all = await balances();
    assert.ok(all.every((b) => b >= 0));
    assert.equal(all.reduce((a, b) => a + b, 0), 13_000);
  });
});
