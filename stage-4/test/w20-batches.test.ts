// W20: POST /correction-batches: settlement members, combined funds and history.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import { Client, expectError, fixture, login, request, reset, type Server, startServer, user } from './helpers.ts';

let server: Server;
let port: number;
let ada: Client; // the settlement operator
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
const ENTRY_FIELDS = ['balance_after', 'delta', 'effective_at', 'payment', 'recorded_at', 'revision'];
const microBefore = (ts: string) => new Date(Date.parse(ts) - 1).toISOString().replace('Z', '999Z');
const msAfter = (ts: string, ms: number) => new Date(Date.parse(ts) + ms).toISOString();
const batch = (c: Client, corrections: unknown, k = key()) => c.post('/correction-batches', { json: { corrections }, key: k });
const item = (p: any, amount: number, extra: Record<string, unknown> = {}) => ({
  payment_id: p.payment_id, expected_revision: 1, amount, effective_at: p.created_at, reason: 'fix', ...extra,
});
const accepted = async (c: Client, corrections: unknown, k = key()) => {
  const reply = await batch(c, corrections, k);
  assert.equal(reply.status, 201, reply.text);
  return reply.body;
};
const correct = (c: Client, id: string, json: unknown, k = key()) => c.post(`/payments/${id}/corrections`, { json, key: k });
const pay = async (from: Client, to: string, amount: number, extra: Record<string, unknown> = {}) => {
  const reply = await from.post('/payments', { json: { to_handle: to, amount, ...extra }, key: key() });
  assert.equal(reply.status, 201, reply.text);
  return reply.body;
};
const settle = async (transfers: unknown[], k = key()) => {
  const reply = await ada.post('/settlements', { json: { transfers }, key: k });
  assert.equal(reply.status, 201, reply.text);
  return reply.body;
};
const totals = async () => Promise.all([ada, bob, cy].map(async (c) => (await c.get('/me')).body.total));
const revisions = async (c: Client, id: string) => (await c.get(`/payments/${id}/revisions`)).body.revisions;
const relogin = async () => {
  [ada, bob, cy] = await Promise.all(['ada', 'bob', 'cy'].map((h) => login(port, h)));
};

describe('a correction batch (W20.1)', () => {
  it('appends revision n + 1 to each payment in input order, all at one recorded_at with the batch id', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const q = await pay(bob, 'cy', 300);
    assert.equal((await correct(ada, p.payment_id, { expected_revision: 1, amount: 900, effective_at: p.created_at, reason: 'r2' })).status, 201);
    const effective = '2020-01-01T05:30:00.10+05:30';
    const body = await accepted(ada, [
      item(q, 200, { reason: 'less', effective_at: effective, extra: 'ignored' }),
      item(p, 800, { expected_revision: 2, reason: 'again' }),
    ]);
    assert.deepEqual(Object.keys(body).sort(), ['correction_batch_id', 'recorded_at', 'revisions']);
    assert.match(body.correction_batch_id, /^cb_/);
    assert.match(body.recorded_at, TS_RE);
    assert.deepEqual(body.revisions, [
      { payment_id: q.payment_id, revision: 2, amount: 200, effective_at: effective, recorded_at: body.recorded_at, reason: 'less', correction_batch_id: body.correction_batch_id },
      { payment_id: p.payment_id, revision: 3, amount: 800, effective_at: p.created_at, recorded_at: body.recorded_at, reason: 'again', correction_batch_id: body.correction_batch_id },
    ]);
    assert.deepEqual(await totals(), [9_200, 3_100, 700]);

    const listed = await revisions(ada, p.payment_id);
    assert.deepEqual(listed, await revisions(bob, p.payment_id));
    assert.deepEqual(listed.map((r: any) => Object.keys(r).sort()), [REVISION_FIELDS, REVISION_FIELDS, [...REVISION_FIELDS, 'correction_batch_id'].sort()]);
    assert.deepEqual(listed[2], body.revisions[1]);
    assert.ok(body.recorded_at > listed[1].recorded_at, 'later than the payment\'s previous recorded_at');
    assert.ok(body.recorded_at > q.created_at);
    assert.deepEqual((await revisions(cy, q.payment_id))[1], body.revisions[0]);
    // A statement entry keeps stage 3's fields.
    const [entry] = (await cy.get('/statement')).body.entries;
    assert.deepEqual(Object.keys(entry).sort(), ENTRY_FIELDS);
    assert.deepEqual([entry.revision, entry.payment.amount, entry.effective_at, entry.recorded_at], [2, 200, effective, body.recorded_at]);
  });

  it('gives two batches in one millisecond strictly increasing recorded_at', async () => {
    const p = await pay(ada, 'bob', 100);
    const q = await pay(ada, 'cy', 100);
    const [a, b] = await Promise.all([batch(ada, [item(p, 90)]), batch(ada, [item(q, 90)])]);
    assert.deepEqual([a.status, b.status], [201, 201]);
    assert.notEqual(a.body.recorded_at, b.body.recorded_at);
    assert.notEqual(a.body.correction_batch_id, b.body.correction_batch_id);
  });
});

describe('who may send a batch (W20.2, D95, D96)', () => {
  it('is 401 without a token, and 403 for a non-operator before the key and the body', async () => {
    const p = await pay(bob, 'cy', 100);
    expectError(await request(port, 'POST', '/correction-batches', { json: { corrections: [item(p, 1)] }, key: key() }), 401, 'unauthenticated');
    expectError(await bob.post('/correction-batches', { json: { corrections: [item(p, 1)] }, key: key() }), 403, 'forbidden');
    expectError(await bob.post('/correction-batches', { json: { corrections: [item(p, 1)] } }), 403, 'forbidden');
    expectError(await bob.post('/correction-batches', { raw: '{"corrections": [', key: key() }), 403, 'forbidden');
    expectError(await bob.post('/correction-batches', { raw: '{' }), 403, 'forbidden');
    expectError(await ada.post('/correction-batches', { json: { corrections: [item(p, 1)] } }), 400, 'missing_idempotency_key');
    expectError(await ada.post('/correction-batches', { raw: '{"corrections": [', key: key() }), 400, 'malformed_request');
    assert.deepEqual(await totals(), [10_000, 2_400, 600]);
  });

  it('lets the operator correct any payment between other users, private ones included, but read revisions only as a party', async () => {
    const p = await pay(bob, 'cy', 100, { visibility: 'private' });
    const ask = (await cy.post('/requests', { json: { payer_handle: 'bob', amount: 50 }, key: key() })).body;
    const viaRequest = (await bob.post(`/requests/${ask.request_id}/pay`, { json: { visibility: 'private' }, key: key() })).body;
    const body = await accepted(ada, [item(p, 60), item(viaRequest, 10)]);
    assert.deepEqual(await totals(), [10_000, 2_500 - 60 - 10, 500 + 70]);
    expectError(await ada.get(`/payments/${p.payment_id}/revisions`), 404, 'not_found');
    assert.deepEqual((await revisions(bob, p.payment_id))[1], body.revisions[0]);
    assert.deepEqual((await revisions(cy, viaRequest.payment_id))[1], body.revisions[1]);
    assert.deepEqual((await ada.get('/activity')).body.payments, [], 'the operator still cannot see private items');
  });
});

describe('batch idempotency, the tenth path (W20.3)', () => {
  it('replays, refuses reuse, claims nothing on failure and scopes keys by path', async () => {
    const p = await pay(ada, 'bob', 1_000);
    expectError(await ada.post('/correction-batches', { json: { corrections: [item(p, 1)] }, key: '' }), 400, 'missing_idempotency_key');
    expectError(await ada.post('/correction-batches', { json: { corrections: [item(p, 1)] }, key: 'k'.repeat(256) }), 422, 'validation_failed');
    const k = key();
    const first = await accepted(ada, [item(p, 900)], k);
    assert.equal((await correct(ada, p.payment_id, { expected_revision: 2, amount: 800, effective_at: p.created_at, reason: 'later' })).status, 201);
    const replay = await batch(ada, [item(p, 900)], k);
    assert.deepEqual([replay.status, replay.body], [200, first], 'the original body after newer revisions');
    expectError(await batch(ada, [item(p, 901)], k), 409, 'idempotency_key_reuse');
    expectError(await ada.post('/correction-batches', { json: { corrections: 'x' }, key: k }), 409, 'idempotency_key_reuse');
    assert.deepEqual(await totals(), [9_200, 3_300, 500], 'a replay moves nothing');

    const failed = key();
    expectError(await batch(ada, [item(p, 700)], failed), 409, 'stale_revision');
    const later = await accepted(ada, [item(p, 700, { expected_revision: 3 })], failed);
    assert.equal(later.revisions[0].revision, 4);
    const samePath = await ada.post('/payments', { json: { to_handle: 'cy', amount: 1 }, key: k });
    assert.equal(samePath.status, 201, 'the same key on another path is a first use');
  });
});

describe('the batch shape (W20.4)', () => {
  it('is 422 before any item is examined', async () => {
    const p = await pay(ada, 'bob', 100);
    const unknown = { ...item(p, 1), payment_id: 'p_none' };
    for (const body of [{}, { corrections: null }, { corrections: 'x' }, { corrections: {} }, { corrections: [] },
      { corrections: Array.from({ length: 33 }, (_, i) => ({ ...unknown, payment_id: `p_${i}` })) },
      { corrections: [unknown, 5] }, { corrections: [unknown, null] }, { corrections: [unknown, [item(p, 1)]] },
      { corrections: [unknown, item(p, 1), item(p, 2)] }]) {
      expectError(await ada.post('/correction-batches', { json: body, key: key() }), 422, 'validation_failed');
    }
    expectError(await ada.post('/correction-batches', { raw: '[]', key: key() }), 400, 'malformed_request');
    // Distinct payment ids are compared as strings; a non-string id is an item error.
    expectError(await batch(ada, [unknown, { ...item(p, 1), payment_id: 5 }, { ...item(p, 1), payment_id: 5 }]), 404, 'not_found');
  });

  it('accepts 32 items', async () => {
    const payments = [];
    for (let i = 0; i < 32; i++) payments.push(await pay(ada, ['bob', 'cy'][i % 2], 10));
    const body = await accepted(ada, payments.map((p) => item(p, 9)), key());
    assert.equal(body.revisions.length, 32);
    assert.deepEqual(body.revisions.map((r: any) => r.payment_id), payments.map((p) => p.payment_id));
    assert.deepEqual(await totals(), [10_000 - 32 * 9, 2_500 + 16 * 9, 500 + 16 * 9]);
  });
});

describe('batch items (W20.5)', () => {
  it('checks every correction field, 422, in input order', async () => {
    const p = await pay(ada, 'bob', 100);
    const fresh = (await pay(ada, 'cy', 1)).created_at;
    const bad = [
      { payment_id: undefined }, { payment_id: null }, { payment_id: 7 }, { expected_revision: undefined }, { expected_revision: 0 },
      { expected_revision: '1' }, { amount: -1 }, { amount: 1.5 }, { amount: 1_000_000_001 }, { amount: null },
      { effective_at: '2020-01-01' }, { effective_at: 'x' }, { effective_at: msAfter(fresh, 900) }, { effective_at: '9999-01-01T00:00:00Z' },
      { reason: '' }, { reason: 'r'.repeat(201) }, { reason: 5 }, { reason: undefined },
    ];
    for (const change of bad) {
      const body: Record<string, unknown> = { ...item(p, 50), ...change };
      for (const k of Object.keys(change)) if (body[k] === undefined) delete body[k];
      expectError(await batch(ada, [body]), 422, 'validation_failed');
    }
    assert.deepEqual(await totals(), [9_899, 2_600, 501]);
  });

  it('is 404 for an unknown payment, 422 for a capture or a refund, 409 when stale, 422 below the refunded total', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const hold = (await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 300 }, key: key() })).body;
    const capture = (await bob.post(`/authorizations/${hold.authorization_id}/capture`, { json: {}, key: key() })).body;
    const r = (await bob.post(`/payments/${p.payment_id}/refunds`, { json: { amount: 400 }, key: key() })).body;
    expectError(await batch(ada, [{ ...item(p, 1), payment_id: 'p_none' }]), 404, 'not_found');
    expectError(await batch(ada, [item(capture, 1)]), 422, 'linked_payment_immutable');
    expectError(await batch(ada, [item(capture, 1, { expected_revision: 9 })]), 422, 'linked_payment_immutable');
    expectError(await batch(ada, [item(r, 1)]), 422, 'linked_payment_immutable');
    expectError(await batch(ada, [item(p, 500, { expected_revision: 2 })]), 409, 'stale_revision');
    expectError(await batch(ada, [item(p, 300, { expected_revision: 2 })]), 409, 'stale_revision');
    expectError(await batch(ada, [item(p, 399)]), 422, 'refund_exceeds_payment');
    // Exactly the refunded total is accepted, and then nothing more can be refunded (W19.3).
    await accepted(ada, [item(p, 400)]);
    expectError(await bob.post(`/payments/${p.payment_id}/refunds`, { json: { amount: 1 }, key: key() }), 422, 'refund_exceeds_payment');
  });

  it('answers with the first failing item', async () => {
    const p = await pay(ada, 'bob', 100);
    const unknown = { ...item(p, 1), payment_id: 'p_none' };
    const invalidItem = item(p, -1);
    expectError(await batch(ada, [unknown, invalidItem]), 404, 'not_found');
    expectError(await batch(ada, [invalidItem, unknown]), 422, 'validation_failed');
    expectError(await batch(ada, [item(p, 1, { expected_revision: 2 }), unknown]), 409, 'stale_revision');
    expectError(await batch(ada, [unknown, item(p, 1, { expected_revision: 2 })]), 404, 'not_found');
  });

  it('allows no tolerance on effective_at: every revision takes effect at or before its recorded_at', async () => {
    const p = await pay(ada, 'bob', 100);
    expectError(await batch(ada, [item(p, 50, { effective_at: msAfter(p.created_at, 900) })]), 422, 'validation_failed');
    const latest = (await pay(ada, 'cy', 1)).created_at;
    const body = await accepted(ada, [item(p, 50, { effective_at: latest })]);
    assert.ok(body.revisions[0].effective_at <= body.recorded_at);
  });
});

describe('settlement members in a batch (W20.6, D98)', () => {
  it('needs every member, at one instant whatever its spelling', async () => {
    const s = await settle([{ from_handle: 'ada', to_handle: 'bob', amount: 50 }, { from_handle: 'bob', to_handle: 'cy', amount: 20 }]);
    const [m1, m2] = s.payments;
    const other = await pay(ada, 'cy', 10);
    expectError(await batch(ada, [item(m1, 40)]), 422, 'incomplete_settlement');
    expectError(await batch(ada, [item(other, 5), item(m2, 10)]), 422, 'incomplete_settlement');
    expectError(await batch(ada, [item(m1, 40, { effective_at: '2020-01-01T00:00:00Z' }), item(m2, 10)]), 422, 'validation_failed');
    expectError(await batch(ada, [item(m1, 40, { effective_at: '2020-01-01T00:00:00.5Z' }), item(m2, 10, { effective_at: '2020-01-01T00:00:00.500001Z' })]), 422, 'validation_failed');
    expectError(await correct(ada, m1.payment_id, { expected_revision: 1, amount: 40, effective_at: m1.created_at, reason: 'x' }), 422, 'linked_payment_immutable');
    assert.deepEqual(await totals(), [9_940, 2_530, 530], 'nothing moved');

    const zeros = await accepted(ada, [item(m1, 40, { effective_at: '2020-01-01T00:00:00.5Z' }), item(m2, 15, { effective_at: '2020-01-01T00:00:00.500Z' })]);
    assert.deepEqual(zeros.revisions.map((r: any) => r.effective_at), ['2020-01-01T00:00:00.5Z', '2020-01-01T00:00:00.500Z']);
    const spellings = await accepted(ada, [
      item(other, 5),
      item(m2, 10, { expected_revision: 2, effective_at: '2020-01-01T05:30:00+05:30' }),
      item(m1, 30, { expected_revision: 2, effective_at: '2020-01-01T00:00:00Z' }),
    ]);
    assert.deepEqual(spellings.revisions.map((r: any) => [r.payment_id, r.revision, r.amount]),
      [[other.payment_id, 2, 5], [m2.payment_id, 3, 10], [m1.payment_id, 3, 30]]);
    assert.deepEqual(await totals(), [10_000 - 30 - 5, 2_500 + 30 - 10, 500 + 10 + 5]);
    // A nonmember is still correctable alone.
    assert.equal((await correct(ada, other.payment_id, { expected_revision: 2, amount: 4, effective_at: other.created_at, reason: 'x' })).status, 201);
  });

  it('finds seeded members by their settlement_id', async () => {
    await reset(port, fixture({
      settlement_operator_ids: ['u_ada'],
      payments: [
        { id: 'p_s1', from_user_id: 'u_bob', to_user_id: 'u_cy', amount: 100, settlement_id: 's_old', created_at: '2020-01-01T00:00:00Z' },
        { id: 'p_s2', from_user_id: 'u_cy', to_user_id: 'u_ada', amount: 50, settlement_id: 's_old', created_at: '2020-01-01T00:00:00Z' },
      ],
    }));
    await relogin();
    const one = { payment_id: 'p_s1', expected_revision: 1, amount: 0, effective_at: '2020-01-01T00:00:00Z', reason: 'undo' };
    expectError(await batch(ada, [one]), 422, 'incomplete_settlement');
    await accepted(ada, [one, { ...one, payment_id: 'p_s2' }]);
    assert.deepEqual(await totals(), [10_000 - 50, 2_500 + 100, 500 - 100 + 50]);
  });
});

describe('combined funds and history (W20.7, D99)', () => {
  it('judges the combined effect: debits each unaffordable alone are accepted together', async () => {
    const p1 = await pay(bob, 'cy', 400);
    const p2 = await pay(cy, 'bob', 900);
    assert.equal((await cy.get('/me')).body.available, 0);
    expectError(await correct(bob, p1.payment_id, { expected_revision: 1, amount: 0, effective_at: p1.created_at, reason: 'x' }), 409, 'insufficient_funds');
    expectError(await batch(ada, [item(p1, 0)]), 409, 'insufficient_funds');
    await accepted(ada, [item(p1, 0), item(p2, 400)]);
    assert.deepEqual(await totals(), [10_000, 2_900, 100]);
  });

  it('accepts a batch leaving available at exactly 0; one unit more, because of an open hold, is 409', async () => {
    for (const [holdAmount, status] of [[501, 409], [500, 201]] as const) {
      await reset(port, fixture({ settlement_operator_ids: ['u_ada'] }));
      await relogin();
      const p1 = await pay(ada, 'cy', 1_000);
      const p2 = await pay(bob, 'cy', 500);
      assert.equal((await cy.post('/authorizations', { json: { to_handle: 'bob', amount: holdAmount }, key: key() })).status, 201);
      const k = key();
      const reply = await batch(ada, [item(p1, 0), item(p2, 0)], k);
      assert.equal(reply.status, status, reply.text);
      if (status === 409) {
        expectError(reply, 409, 'insufficient_funds');
        assert.deepEqual(await totals(), [9_000, 2_000, 2_000]);
      } else {
        const me = (await cy.get('/me')).body;
        assert.deepEqual([me.total, me.held, me.available], [500, 500, 0]);
      }
    }
  });

  it('refuses a batch that would take a wallet above 2^53', async () => {
    await reset(port, fixture({ settlement_operator_ids: ['u_ada'], users: [user('ada', 2 ** 53 - 100), user('bob', 1_000), user('cy', 0)] }));
    await relogin();
    const q = await pay(bob, 'ada', 100);
    expectError(await batch(ada, [item(q, 101)]), 422, 'validation_failed');
    await accepted(ada, [item(q, 100)]);
    assert.deepEqual(await totals(), [2 ** 53, 900, 0]);
  });

  it('is historical_overdraft from the new revisions together, when each alone would pass', async () => {
    for (const alone of [0, 1]) {
      await reset(port, fixture({ settlement_operator_ids: ['u_ada'] }));
      await relogin();
      const q1 = await pay(bob, 'cy', 1_000);
      const q2 = await pay(bob, 'ada', 1_000);
      await pay(ada, 'bob', 2_000);
      const k = key();
      expectError(await batch(ada, [item(q1, 1_300), item(q2, 1_300)], k), 409, 'historical_overdraft');
      assert.deepEqual(await totals(), [9_000, 2_500, 1_500]);
      // Either one alone keeps bob at 200 or more at q2's instant; the refused batch left its key free.
      await accepted(ada, [item([q1, q2][alone], 1_300)], k);
      assert.equal((await bob.get('/me')).body.total, 2_200);
    }
  });

  it('combines one instant\'s movements, even with the debit created first; a dip between two instants is 409', async () => {
    const q = await pay(bob, 'cy', 1_000);
    const p = await pay(ada, 'bob', 2_000);
    // bob had 2 500. q raised to 4 000 needs p's 2 000 at the same instant.
    expectError(await batch(ada, [item(q, 4_000), item(p, 2_000)]), 409, 'historical_overdraft');
    const body = await accepted(ada, [item(q, 4_000, { effective_at: p.created_at }), item(p, 2_000)]);
    assert.equal(body.revisions[0].effective_at, p.created_at);
    assert.deepEqual(await totals(), [8_000, 500, 4_500]);
  });

  it('answers item errors, then completeness, then the instants rule, then the funds, then history', async () => {
    const s = await settle([{ from_handle: 'bob', to_handle: 'cy', amount: 50 }, { from_handle: 'cy', to_handle: 'bob', amount: 20 }]);
    const [m1, m2] = s.payments;
    const big = await pay(cy, 'ada', 500);
    const q1 = await pay(bob, 'cy', 1_000);
    const q2 = await pay(bob, 'ada', 1_000);
    await pay(ada, 'bob', 2_000);
    // cy holds 1 030 and cannot give 4 500 more for `big`; q1 and q2 raised together take bob
    // below zero at q2's instant.
    const unaffordable = item(big, 5_000);
    const unknown = { ...item(m1, 0), payment_id: 'p_none' };
    expectError(await batch(ada, [item(m1, 0), unknown]), 404, 'not_found');
    expectError(await batch(ada, [item(m1, 0), unaffordable]), 422, 'incomplete_settlement');
    expectError(await batch(ada, [item(m1, 0), item(m2, 0, { effective_at: '2020-01-01T00:00:00Z' }), unaffordable]), 422, 'validation_failed');
    expectError(await batch(ada, [item(m1, 0), item(m2, 0), unaffordable, item(q1, 1_300), item(q2, 1_300)]), 409, 'insufficient_funds');
    expectError(await batch(ada, [item(m1, 0), item(m2, 0), item(q1, 1_300), item(q2, 1_300)]), 409, 'historical_overdraft');
    await accepted(ada, [item(m1, 0), item(m2, 0), item(q1, 1_300)]);
  });
});

describe('a rejected batch (W20.8)', () => {
  it('changes no balance, revision, statement or snapshot, and leaves its key free', async () => {
    const p = await pay(ada, 'bob', 1_000);
    const q = await pay(bob, 'cy', 3_000);
    await pay(ada, 'bob', 2_000);
    const old = (await bob.get('/statement')).body;
    const state = async () => ({
      totals: await totals(),
      revisions: [await revisions(bob, p.payment_id), await revisions(bob, q.payment_id)],
      statement: (({ snapshot, ...rest }) => rest)((await bob.get('/statement')).body),
      snapshot: (await bob.get(`/statement?snapshot=${old.snapshot}`)).body,
    });
    const before = await state();
    const k = key();
    // bob can afford it now, but without p he could not have paid q.
    expectError(await batch(ada, [item(q, 2_900), item(p, 0)], k), 409, 'historical_overdraft');
    assert.deepEqual(await state(), before);
    assert.deepEqual(before.snapshot, old);
    const ok = await accepted(ada, [item(q, 2_900), item(p, 400)], k);
    assert.equal(ok.revisions.length, 2);
  });
});

describe('originals and history after a batch (W20.9)', () => {
  it('keeps payments, feed items and settlement replays, and shows the new revisions in new statements only', async () => {
    const settleKey = key();
    const transfers = [{ from_handle: 'ada', to_handle: 'bob', amount: 50 }, { from_handle: 'bob', to_handle: 'cy', amount: 20 }];
    const s = await settle(transfers, settleKey);
    const [m1, m2] = s.payments;
    const feed = (await bob.get('/activity')).body;
    const old = (await bob.get('/statement')).body;
    const body = await accepted(ada, [item(m1, 0), item(m2, 20)]);
    const t = body.recorded_at;

    assert.deepEqual((await bob.get('/activity')).body, feed);
    const replay = await ada.post('/settlements', { json: { transfers }, key: settleKey });
    assert.deepEqual([replay.status, replay.body], [200, s]);
    assert.deepEqual((await bob.get(`/statement?snapshot=${old.snapshot}`)).body, old);

    const now = (await bob.get('/statement')).body;
    assert.deepEqual(now.entries.map((e: any) => [e.payment.payment_id, e.payment.amount, e.delta, e.revision, e.recorded_at]),
      [m1.payment_id, m2.payment_id].sort().map((id) => (id === m1.payment_id ? [id, 0, 0, 2, t] : [id, 20, -20, 2, t])));
    assert.equal(now.entries.find((e: any) => e.payment.payment_id === m1.payment_id).payment.created_at, m1.created_at);
    const known = async (k: string) => (await bob.get(`/statement?known_at=${encodeURIComponent(k)}`)).body.entries.map((e: any) => [e.payment.payment_id, e.revision]);
    assert.deepEqual((await known(microBefore(t))).map((e: any[]) => e[1]), [1, 1]);
    assert.deepEqual((await known(t)).map((e: any[]) => e[1]), [2, 2]);
    assert.equal((await bob.get(`/me?known_at=${encodeURIComponent(microBefore(t))}`)).body.total, 2_530);
    assert.equal((await bob.get(`/me?known_at=${encodeURIComponent(t)}`)).body.total, 2_480);
  });
});

describe('concurrent corrections (W20.10, D105)', () => {
  it('lets one of a batch and a single correction on one revision succeed', async () => {
    for (let round = 0; round < 5; round++) {
      const p = await pay(ada, 'bob', 100);
      const replies = await Promise.all([
        batch(ada, [item(p, 90)]),
        correct(ada, p.payment_id, { expected_revision: 1, amount: 80, effective_at: p.created_at, reason: 'single' }),
      ]);
      assert.equal(replies.filter((r) => r.status === 201).length, 1);
      for (const r of replies) if (r.status !== 201) expectError(r, 409, 'stale_revision');
      assert.equal((await revisions(ada, p.payment_id)).length, 2);
    }
  });

  it('lets one of two overlapping batches succeed, and one of 50 over one settlement, moving money once', async () => {
    const p = await pay(ada, 'bob', 100);
    const q = await pay(ada, 'cy', 100);
    const r = await pay(bob, 'cy', 100);
    const two = await Promise.all([batch(ada, [item(p, 90), item(q, 90)]), batch(ada, [item(r, 90), item(q, 80)])]);
    assert.deepEqual(two.map((x) => x.status).sort(), [201, 409]);

    const s = await settle([{ from_handle: 'ada', to_handle: 'bob', amount: 500 }, { from_handle: 'bob', to_handle: 'cy', amount: 300 }]);
    const before = await totals();
    const replies = await Promise.all(Array.from({ length: 50 }, (_, i) => batch(ada, [item(s.payments[0], 400 - i), item(s.payments[1], 300)])));
    const won = replies.filter((x) => x.status === 201);
    assert.equal(won.length, 1);
    for (const x of replies) if (x.status !== 201) expectError(x, 409, 'stale_revision');
    const fall = 500 - won[0].body.revisions[0].amount;
    assert.deepEqual(await totals(), [before[0] + fall, before[1] - fall, before[2]]);
  });
});
