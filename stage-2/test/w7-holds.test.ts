// W7: holds API (authorizations, captures, voids, expiry, funds judged on `available`).

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import {
  Client, expectError, fixture, login, request, reset, startServer, user,
  type Reply, type Server,
} from './helpers.ts';

let server: Server;
let port: number;
let ada: Client; // 10 000
let bob: Client; // 2 500
let cy: Client; // 500

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
const AUTHORIZATION_FIELDS = [
  'amount', 'authorization_id', 'captured_amount', 'created_at', 'currency', 'expires_at', 'from_handle',
  'from_user_id', 'note', 'payment_id', 'payment_ids', 'remaining_amount', 'status', 'to_handle', 'to_user_id',
  'visibility',
];
const PAYMENT_FIELDS = [
  'amount', 'authorization_id', 'created_at', 'currency', 'from_handle', 'from_user_id', 'note', 'payment_id',
  'request_id', 'settlement_id', 'to_handle', 'to_user_id', 'visibility',
];

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const authorize = (c: Client, json: unknown, k: string = key()) => c.post('/authorizations', { json, key: k });
const capture = (c: Client, id: string, json: unknown = {}, k: string = key()) =>
  c.post(`/authorizations/${encodeURIComponent(id)}/capture`, { json, key: k });
const voidIt = (c: Client, id: string, opts = {}) => c.post(`/authorizations/${encodeURIComponent(id)}/void`, opts);
const list = async (c: Client, query = '') => {
  const reply = await c.get(`/authorizations${query}`);
  assert.equal(reply.status, 200, reply.text);
  return reply.body.authorizations as any[];
};
const money = async (c: Client) => {
  const { total, available, held, balance } = (await c.get('/me')).body;
  assert.equal(balance, total);
  assert.equal(available, total - held);
  return { total, available, held };
};
const ids = (items: any[]) => items.map((a) => a.authorization_id);
const hold = async (c: Client, to: string, amount: number, extra: Record<string, unknown> = {}) => {
  const reply = await authorize(c, { to_handle: to, amount, ...extra });
  assert.equal(reply.status, 201, reply.text);
  return reply.body;
};
const seedAuth = (id: string, from: string, to: string, amount: number, extra: Record<string, unknown> = {}) => ({
  id, from_user_id: `u_${from}`, to_user_id: `u_${to}`, amount, expires_at: inHours(1), ...extra,
});
const inHours = (h: number) => new Date(Date.now() + h * 3_600_000).toISOString().replace('Z', '+00:00');
const totals = async () => {
  const all = await Promise.all([ada, bob, cy].map(money));
  for (const m of all) {
    assert.ok(m.total >= 0 && m.available >= 0 && m.held >= 0 && m.held <= m.total, JSON.stringify(m));
  }
  return all;
};
const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

describe('GET /me money fields (W7.1)', () => {
  it('has exactly the Me fields; with no holds balance, total and available agree and held is 0', async () => {
    const body = (await bob.get('/me')).body;
    assert.deepEqual(Object.keys(body), [
      'user_id', 'display_name', 'handle', 'balance', 'total', 'available', 'held', 'currency', 'minor_units',
    ]);
    assert.deepEqual([body.balance, body.total, body.available, body.held], [2500, 2500, 2500, 0]);
  });

  it('shows available = total - held while holds are open', async () => {
    await hold(ada, 'bob', 2000);
    await hold(ada, 'cy', 500);
    assert.deepEqual(await money(ada), { total: 10_000, available: 7500, held: 2500 });
    assert.deepEqual(await money(bob), { total: 2500, available: 2500, held: 0 });
  });
});

describe('POST /authorizations (W7.2)', () => {
  it('returns exactly the authorization, open and uncaptured, expiring after the TTL', async () => {
    const reply = await authorize(ada, { to_handle: 'bob', amount: 2000, note: 'deposit', visibility: 'private' });
    assert.equal(reply.status, 201);
    const a = reply.body;
    assert.deepEqual(Object.keys(a).sort(), AUTHORIZATION_FIELDS);
    assert.match(a.authorization_id, /^a_[A-Za-z0-9_-]{16}$/);
    assert.deepEqual(
      [a.from_user_id, a.from_handle, a.to_user_id, a.to_handle, a.amount, a.captured_amount, a.remaining_amount,
        a.currency, a.note, a.visibility, a.status, a.payment_id, a.payment_ids],
      ['u_ada', 'ada', 'u_bob', 'bob', 2000, 0, 2000, 'EUR', 'deposit', 'private', 'open', null, []],
    );
    assert.match(a.created_at, TS_RE);
    assert.match(a.expires_at, TS_RE);
    assert.equal(Date.parse(a.expires_at) - Date.parse(a.created_at), 600_000);
    const defaults = await hold(ada, 'cy', 1);
    assert.equal(defaults.note, '');
    assert.equal(defaults.visibility, 'public');
  });

  it('uses the fixture TTL', async () => {
    await reset(port, fixture({ authorization_ttl_seconds: 90 }));
    const a = await hold(await login(port, 'ada'), 'bob', 5);
    assert.equal(Date.parse(a.expires_at) - Date.parse(a.created_at), 90_000);
  });

  it('moves no money and never appears in any feed', async () => {
    await hold(ada, 'bob', 2000, { visibility: 'public' });
    assert.deepEqual((await totals()).map((m) => m.total), [10_000, 2500, 500]);
    for (const c of [ada, bob, cy]) assert.deepEqual((await c.get('/activity')).body.payments, []);
  });

  it('judges funds on available: exactly available succeeds, one unit more is 409', async () => {
    await hold(ada, 'bob', 6000);
    const k = key();
    expectError(await authorize(ada, { to_handle: 'cy', amount: 4001 }, k), 409, 'insufficient_funds');
    assert.deepEqual(await money(ada), { total: 10_000, available: 4000, held: 6000 });
    assert.equal((await authorize(ada, { to_handle: 'cy', amount: 4000 }, k)).status, 201, 'the refused key was not claimed');
    assert.deepEqual(await money(ada), { total: 10_000, available: 0, held: 10_000 });
    expectError(await authorize(ada, { to_handle: 'cy', amount: 1 }), 409, 'insufficient_funds');
  });

  it('answers every error row in the POST /payments precedence', async () => {
    expectError(await request(port, 'POST', '/authorizations', { json: { to_handle: 'bob', amount: 1 }, key: key() }),
      401, 'unauthenticated');
    expectError(await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 1 } }), 400, 'missing_idempotency_key');
    expectError(await ada.post('/authorizations', { json: { to_handle: 'bob', amount: 1 }, key: 'k'.repeat(256) }),
      422, 'validation_failed');
    expectError(await ada.post('/authorizations', { raw: '{nope', key: key() }), 400, 'malformed_request');
    expectError(await authorize(ada, { to_handle: 5, amount: 'x' }), 400, 'malformed_request');
    expectError(await authorize(ada, { to_handle: null, amount: 1 }), 400, 'malformed_request');
    for (const body of [
      { amount: 1 }, { to_handle: 'bob' }, { to_handle: 'bob', amount: 0 }, { to_handle: 'bob', amount: -1 },
      { to_handle: 'bob', amount: 1.5 }, { to_handle: 'bob', amount: 1_000_000_001 }, { to_handle: 'bob', amount: '10' },
      { to_handle: 'bob', amount: null }, { to_handle: 'bob', amount: 1, note: 'x'.repeat(201) },
      { to_handle: 'bob', amount: 1, note: null }, { to_handle: 'bob', amount: 1, visibility: 'Private' },
      { to_handle: 'nobody', amount: 0 },
    ]) {
      expectError(await authorize(ada, body), 422, 'validation_failed');
    }
    expectError(await authorize(ada, { to_handle: 'nobody', amount: 99_999 }), 404, 'not_found');
    expectError(await authorize(ada, { to_handle: 'ada', amount: 99_999 }), 422, 'self_payment');
    expectError(await authorize(ada, { to_handle: 'bob', amount: 10_001 }), 409, 'insufficient_funds');
    assert.equal((await authorize(ada, { to_handle: 'bob', amount: 5000, colour: 'blue' })).status, 201);
    assert.equal((await authorize(ada, { to_handle: 'bob', amount: 1, note: '😀'.repeat(200) })).status, 201);
  });

  it('follows the idempotency table, scoped by user and path', async () => {
    const k = key();
    const body = { to_handle: 'bob', amount: 100 };
    const first = await authorize(ada, body, k);
    assert.equal(first.status, 201);
    const replay = await authorize(ada, { amount: 100, to_handle: 'bob' }, k);
    assert.equal(replay.status, 200);
    assert.deepEqual(replay.body, first.body);
    expectError(await authorize(ada, { to_handle: 'bob', amount: 101 }, k), 409, 'idempotency_key_reuse');
    const other = await authorize(ada, body);
    assert.equal(other.status, 201);
    assert.notEqual(other.body.authorization_id, first.body.authorization_id);
    assert.equal((await authorize(bob, { to_handle: 'ada', amount: 100 }, k)).status, 201, 'another user');
    assert.equal((await ada.post('/payments', { json: body, key: k })).status, 201, 'another path');
    assert.deepEqual(await money(ada), { total: 9900, available: 9700, held: 200 });
  });

  it('gives one 201 for 50 concurrent identical first uses', async () => {
    const k = key();
    const replies = await Promise.all(Array.from({ length: 50 }, () => authorize(ada, { to_handle: 'bob', amount: 100 }, k)));
    assert.equal(replies.filter((r) => r.status === 201).length, 1);
    assert.equal(replies.filter((r) => r.status === 200).length, 49);
    for (const r of replies) assert.deepEqual(r.body, replies[0].body);
    assert.deepEqual(await money(ada), { total: 10_000, available: 9900, held: 100 });
  });

  it('replays the original open body after a capture or a void', async () => {
    const k1 = key();
    const a1 = (await authorize(ada, { to_handle: 'bob', amount: 100 }, k1)).body;
    assert.equal((await capture(bob, a1.authorization_id)).status, 201);
    const k2 = key();
    const a2 = (await authorize(ada, { to_handle: 'bob', amount: 200 }, k2)).body;
    assert.equal((await voidIt(ada, a2.authorization_id)).status, 200);
    for (const [k, original, amount] of [[k1, a1, 100], [k2, a2, 200]] as const) {
      const replay = await authorize(ada, { to_handle: 'bob', amount }, k);
      assert.equal(replay.status, 200);
      assert.deepEqual(replay.body, original);
      assert.equal(replay.body.status, 'open');
    }
    assert.deepEqual(await money(ada), { total: 9900, available: 9900, held: 0 });
  });
});

describe('POST /authorizations/{id}/capture (W7.3)', () => {
  it('captures the whole remainder by default and returns exactly the payment', async () => {
    const a = await hold(ada, 'bob', 2000, { note: 'deposit', visibility: 'private' });
    const reply = await capture(bob, a.authorization_id);
    assert.equal(reply.status, 201);
    const p = reply.body;
    assert.deepEqual(Object.keys(p).sort(), PAYMENT_FIELDS);
    assert.deepEqual(
      [p.from_user_id, p.from_handle, p.to_user_id, p.to_handle, p.amount, p.currency, p.note, p.visibility,
        p.request_id, p.settlement_id, p.authorization_id],
      ['u_ada', 'ada', 'u_bob', 'bob', 2000, 'EUR', 'deposit', 'private', null, null, a.authorization_id],
    );
    assert.match(p.payment_id, /^p_/);
    assert.match(p.created_at, TS_RE);
    const [after] = await list(ada);
    assert.deepEqual(
      [after.status, after.captured_amount, after.remaining_amount, after.payment_id, after.payment_ids],
      ['captured', 2000, 0, p.payment_id, [p.payment_id]],
    );
    assert.deepEqual(await money(ada), { total: 8000, available: 8000, held: 0 });
    assert.deepEqual(await money(bob), { total: 4500, available: 4500, held: 0 });
    assert.deepEqual((await ada.get('/activity')).body.payments, [p]);
    assert.deepEqual((await cy.get('/activity')).body.payments, [], 'a private capture follows the feed rule');
  });

  it('a smaller final capture releases the rest in the same step', async () => {
    const a = await hold(ada, 'bob', 2000, { visibility: 'public' });
    assert.deepEqual(await money(ada), { total: 10_000, available: 8000, held: 2000 });
    const p = (await capture(bob, a.authorization_id, { amount: 1500 })).body;
    assert.equal(p.amount, 1500);
    assert.deepEqual(await money(ada), { total: 8500, available: 8500, held: 0 });
    const [after] = await list(bob);
    assert.deepEqual([after.status, after.captured_amount, after.remaining_amount], ['captured', 1500, 0]);
    assert.deepEqual((await cy.get('/activity')).body.payments, [p], 'a public capture is in every feed');
    expectError(await capture(bob, a.authorization_id, { amount: 1 }), 409, 'authorization_not_open');
  });

  it('final:false keeps the rest held; capturing the whole remainder closes it', async () => {
    const a = await hold(ada, 'bob', 2000);
    const p1 = (await capture(bob, a.authorization_id, { amount: 700, final: false })).body;
    let [now] = await list(ada);
    assert.deepEqual([now.status, now.captured_amount, now.remaining_amount, now.payment_id], ['open', 700, 1300, p1.payment_id]);
    assert.deepEqual(await money(ada), { total: 9300, available: 8000, held: 1300 });
    const p2 = (await capture(bob, a.authorization_id, { amount: 300, final: false })).body;
    expectError(await capture(bob, a.authorization_id, { amount: 1001, final: false }), 422, 'capture_exceeds_authorization');
    const p3 = (await capture(bob, a.authorization_id, { final: false })).body;
    assert.equal(p3.amount, 1000);
    [now] = await list(ada);
    assert.deepEqual(
      [now.status, now.captured_amount, now.remaining_amount, now.payment_id, now.payment_ids],
      ['captured', 2000, 0, p3.payment_id, [p1.payment_id, p2.payment_id, p3.payment_id]],
    );
    assert.deepEqual(await money(ada), { total: 8000, available: 8000, held: 0 });
    assert.deepEqual(await money(bob), { total: 4500, available: 4500, held: 0 });
    expectError(await capture(bob, a.authorization_id), 409, 'authorization_not_open');
  });

  it('answers every error row in the D50 order, and a refused key is not claimed', async () => {
    const a = await hold(ada, 'bob', 2000);
    const id = a.authorization_id;
    expectError(await request(port, 'POST', `/authorizations/${id}/capture`, { json: {}, key: key() }), 401, 'unauthenticated');
    expectError(await bob.post(`/authorizations/${id}/capture`, { json: {} }), 400, 'missing_idempotency_key');
    expectError(await bob.post(`/authorizations/${id}/capture`, { raw: '[', key: key() }), 400, 'malformed_request');
    for (const final of [null, 'true', 1, {}, []]) {
      expectError(await capture(bob, id, { final, amount: 'x' }), 400, 'malformed_request');
    }
    for (const amount of [0, -5, 1.5, '10', true, null, []]) {
      expectError(await capture(bob, 'a_missing', { amount }), 422, 'validation_failed');
    }
    expectError(await bob.post('/authorizations/a_missing/capture', { raw: '{"amount": 1e400}', key: key() }),
      422, 'validation_failed');
    expectError(await capture(bob, 'a_missing', { amount: 5 }), 404, 'not_found');
    expectError(await capture(ada, id), 403, 'forbidden');
    expectError(await capture(cy, id, { amount: 1e12 }), 403, 'forbidden');
    for (const amount of [2001, 1_000_000_001, 1e15]) {
      expectError(await capture(bob, id, { amount }), 422, 'capture_exceeds_authorization');
    }
    const k = key();
    expectError(await capture(bob, id, { amount: 2001 }, k), 422, 'capture_exceeds_authorization');
    assert.equal((await capture(bob, id, { amount: 2000 }, k)).status, 201, 'the refused key was not claimed');
    // State before amount: a closed authorization is 409 whatever the amount.
    expectError(await capture(bob, id, { amount: 1e12 }), 409, 'authorization_not_open');
    const v = await hold(ada, 'bob', 50);
    await voidIt(ada, v.authorization_id);
    expectError(await capture(bob, v.authorization_id, { amount: 51 }), 409, 'authorization_not_open');
    expectError(await capture(ada, v.authorization_id), 403, 'forbidden');
    assert.deepEqual(await money(ada), { total: 8000, available: 8000, held: 0 });
  });

  it('replays the original payment, even after the authorization closed, and only for the identical body', async () => {
    const a = await hold(ada, 'bob', 2000);
    const k = key();
    const first = await capture(bob, a.authorization_id, { amount: 700 }, k);
    assert.equal(first.status, 201);
    const replay = await capture(bob, a.authorization_id, { amount: 700 }, k);
    assert.equal(replay.status, 200);
    assert.deepEqual(replay.body, first.body);
    expectError(await capture(bob, a.authorization_id, { amount: 700, final: true }, k), 409, 'idempotency_key_reuse');
    expectError(await capture(bob, a.authorization_id, {}, k), 409, 'idempotency_key_reuse');
    // The canonical path is the decoded id.
    const encoded = await bob.post(`/authorizations/${a.authorization_id.replace('_', '%5F')}/capture`,
      { json: { amount: 700 }, key: k });
    assert.equal(encoded.status, 200);
    assert.deepEqual(await money(ada), { total: 9300, available: 9300, held: 0 });

    const b = await hold(ada, 'bob', 500);
    const k2 = key();
    assert.equal((await capture(bob, b.authorization_id, {}, k2)).status, 201);
    expectError(await capture(bob, b.authorization_id, { amount: 500 }, k2), 409, 'idempotency_key_reuse');
    assert.equal((await capture(bob, b.authorization_id, {}, k2)).status, 200);
    assert.deepEqual(await money(bob), { total: 3700, available: 3700, held: 0 });
  });

  it('refuses to take the receiver above 2^53 and changes nothing', async () => {
    await reset(port, fixture({
      users: [user('ada', 100), user('rich', 2 ** 53 - 10)],
      authorizations: [seedAuth('a_1', 'ada', 'rich', 11)],
    }));
    const [a, rich] = await Promise.all([login(port, 'ada'), login(port, 'rich')]);
    const k = key();
    expectError(await capture(rich, 'a_1', {}, k), 422, 'validation_failed');
    assert.deepEqual(await money(a), { total: 100, available: 89, held: 11 });
    const [still] = await list(a);
    assert.deepEqual([still.status, still.captured_amount, still.payment_ids], ['open', 0, []]);
    assert.equal((await capture(rich, 'a_1', { amount: 10 }, k)).status, 201);
    assert.deepEqual(await money(rich), { total: 2 ** 53, available: 2 ** 53, held: 0 });
    assert.deepEqual(await money(a), { total: 90, available: 90, held: 0 });
  });
});

describe('POST /authorizations/{id}/void (W7.4)', () => {
  it('lets only the payer void, with no key and no body read', async () => {
    const a = await hold(ada, 'bob', 2000);
    expectError(await request(port, 'POST', `/authorizations/${a.authorization_id}/void`), 401, 'unauthenticated');
    expectError(await voidIt(bob, a.authorization_id), 403, 'forbidden');
    expectError(await voidIt(cy, a.authorization_id), 403, 'forbidden');
    expectError(await voidIt(ada, 'a_missing'), 404, 'not_found');
    const reply = await voidIt(ada, a.authorization_id, { raw: '{not json' });
    assert.equal(reply.status, 200);
    assert.deepEqual(Object.keys(reply.body).sort(), AUTHORIZATION_FIELDS);
    assert.deepEqual([reply.body.status, reply.body.remaining_amount, reply.body.captured_amount], ['voided', 0, 0]);
    assert.deepEqual(await money(ada), { total: 10_000, available: 10_000, held: 0 });
    const again = await voidIt(ada, a.authorization_id);
    assert.equal(again.status, 200);
    assert.deepEqual(again.body, reply.body);
  });

  it('keeps the captures of a partially captured authorization', async () => {
    const a = await hold(ada, 'bob', 2000);
    const p = (await capture(bob, a.authorization_id, { amount: 500, final: false })).body;
    const v = (await voidIt(ada, a.authorization_id)).body;
    assert.deepEqual(
      [v.status, v.captured_amount, v.remaining_amount, v.payment_id, v.payment_ids],
      ['voided', 500, 0, p.payment_id, [p.payment_id]],
    );
    assert.deepEqual(await money(ada), { total: 9500, available: 9500, held: 0 });
    expectError(await capture(bob, a.authorization_id, { amount: 1 }), 409, 'authorization_not_open');
  });

  it('refuses captured and expired authorizations with 409', async () => {
    const a = await hold(ada, 'bob', 2000);
    await capture(bob, a.authorization_id);
    expectError(await voidIt(ada, a.authorization_id), 409, 'authorization_not_open');
    await reset(port, fixture({
      authorizations: [
        seedAuth('a_seeded_expired', 'ada', 'bob', 300, { status: 'expired' }),
        seedAuth('a_past', 'ada', 'bob', 300, { expires_at: inHours(-1) }),
      ],
    }));
    const a2 = await login(port, 'ada');
    expectError(await voidIt(a2, 'a_seeded_expired'), 409, 'authorization_not_open');
    expectError(await voidIt(a2, 'a_past'), 409, 'authorization_not_open');
  });
});

describe('GET /authorizations (W7.5)', () => {
  it('lists only the caller\'s, newest first, filtered exactly by direction and status', async () => {
    const out1 = await hold(ada, 'bob', 100);
    const in1 = await hold(bob, 'ada', 200);
    const out2 = await hold(ada, 'bob', 300);
    const other = await hold(bob, 'cy', 50);
    await capture(bob, out2.authorization_id);
    await voidIt(bob, in1.authorization_id);
    assert.deepEqual(ids(await list(ada)), [out2, in1, out1].map((a) => a.authorization_id));
    assert.deepEqual(ids(await list(ada, '?direction=outgoing')), [out2, out1].map((a) => a.authorization_id));
    assert.deepEqual(ids(await list(ada, '?direction=incoming')), [in1.authorization_id]);
    assert.deepEqual(ids(await list(ada, '?status=open')), [out1.authorization_id]);
    assert.deepEqual(ids(await list(ada, '?status=captured&direction=outgoing')), [out2.authorization_id]);
    assert.deepEqual(ids(await list(ada, '?status=voided&direction=outgoing')), []);
    assert.deepEqual(ids(await list(ada, '?status=voided&direction=incoming')), [in1.authorization_id]);
    assert.deepEqual(ids(await list(cy)), [other.authorization_id]);
    assert.deepEqual(ids(await list(bob, '?direction=outgoing')), [other, in1].map((a) => a.authorization_id));
  });

  it('pages with limit, offset and has_more, and refuses invalid values', async () => {
    const made = [];
    for (let i = 0; i < 5; i++) made.unshift((await hold(ada, 'bob', i + 1)).authorization_id);
    let reply = await ada.get('/authorizations?limit=2&offset=1');
    assert.deepEqual([ids(reply.body.authorizations), reply.body.has_more], [made.slice(1, 3), true]);
    reply = await ada.get('/authorizations?limit=2&offset=3');
    assert.deepEqual([ids(reply.body.authorizations), reply.body.has_more], [made.slice(3), false]);
    reply = await ada.get('/authorizations?limit=5&direction=outgoing&direction=incoming');
    assert.deepEqual([ids(reply.body.authorizations), reply.body.has_more], [made, false]);
    for (const q of ['direction=Outgoing', 'direction=', 'direction=both', 'status=OPEN', 'status=', 'status=pending',
      'limit=0', 'limit=201', 'limit=1.0', 'offset=-1', 'offset=x']) {
      expectError(await ada.get(`/authorizations?${q}`), 422, 'validation_failed');
    }
    expectError(await request(port, 'GET', '/authorizations'), 401, 'unauthenticated');
  });

  it('answers JSON for Accept application/json, */* and no Accept', async () => {
    await hold(ada, 'bob', 1);
    for (const headers of [{ accept: 'application/json' }, { accept: '*/*' }, {}]) {
      const reply = await ada.get('/authorizations', { headers });
      assert.equal(reply.status, 200);
      assert.match(String(reply.headers['content-type']), /^application\/json/);
      assert.equal(reply.body.authorizations.length, 1);
    }
  });
});

describe('expiry by the clock (W7.6)', () => {
  it('expires an open authorization at its deadline with no request at the deadline', async () => {
    await reset(port, fixture({ authorization_ttl_seconds: 1 }));
    const [a, b] = await Promise.all([login(port, 'ada'), login(port, 'bob')]);
    const early = await hold(a, 'bob', 1000);
    const late = await hold(a, 'bob', 2000);
    assert.equal(Date.parse(late.expires_at) - Date.parse(late.created_at), 1000);
    const captured = await capture(b, early.authorization_id, { amount: 400 });
    assert.equal(captured.status, 201, 'a capture before the deadline succeeds');
    assert.deepEqual(await money(a), { total: 9600, available: 7600, held: 2000 });
    await sleep(Date.parse(late.expires_at) - Date.now() + 50);
    assert.deepEqual(await money(a), { total: 9600, available: 9600, held: 0 });
    const [item] = await list(a, '?status=expired');
    assert.deepEqual([item.authorization_id, item.status, item.remaining_amount], [late.authorization_id, 'expired', 0]);
    assert.deepEqual(await list(a, '?status=open'), []);
    expectError(await capture(b, late.authorization_id, { amount: 1 }), 409, 'authorization_expired');
    expectError(await capture(b, late.authorization_id, { amount: 99_999 }), 409, 'authorization_expired');
    expectError(await voidIt(a, late.authorization_id), 409, 'authorization_not_open');
    assert.equal((await a.post('/payments', { json: { to_handle: 'cy', amount: 9600 }, key: key() })).status, 201,
      'the released remainder can be spent');
  });

  it('a partially captured authorization that expires keeps its captures and releases the rest', async () => {
    await reset(port, fixture({ authorization_ttl_seconds: 1 }));
    const [a, b] = await Promise.all([login(port, 'ada'), login(port, 'bob')]);
    const h = await hold(a, 'bob', 1000);
    assert.equal(Date.parse(h.expires_at) - Date.parse(h.created_at), 1000);
    const p = (await capture(b, h.authorization_id, { amount: 300, final: false })).body;
    await sleep(Date.parse(h.expires_at) - Date.now() + 50);
    const [item] = await list(b);
    assert.deepEqual(
      [item.status, item.captured_amount, item.remaining_amount, item.payment_ids],
      ['expired', 300, 0, [p.payment_id]],
    );
    assert.deepEqual(await money(a), { total: 9700, available: 9700, held: 0 });
  });

  it('seeded open holds an hour past their deadline read expired right after the reset', async () => {
    await reset(port, fixture({
      users: [user('ada', 100), user('bob', 0)],
      authorizations: [
        seedAuth('a_past', 'ada', 'bob', 1000, { expires_at: inHours(-1) }),
        seedAuth('a_live', 'ada', 'bob', 100, { expires_at: inHours(1) }),
      ],
    }));
    const a = await login(port, 'ada');
    assert.deepEqual(await money(a), { total: 100, available: 0, held: 100 });
    assert.deepEqual((await list(a)).map((x) => [x.authorization_id, x.status, x.remaining_amount]),
      [['a_live', 'open', 100], ['a_past', 'expired', 0]]);
    expectError(await capture(await login(port, 'bob'), 'a_past'), 409, 'authorization_expired');
  });
});

describe('the service clock', () => {
  it('reads and refused writes change nothing, not even the last issued timestamp', async () => {
    await reset(port, fixture({ authorization_ttl_seconds: 1 }));
    const [a, b] = await Promise.all([login(port, 'ada'), login(port, 'bob')]);
    const h = await hold(a, 'bob', 1000);
    await sleep(Date.parse(h.expires_at) - Date.now() + 50);
    const snapshot = (await request(port, 'GET', '/_test/export')).body;
    await sleep(20);
    await a.get('/me');
    await a.get('/authorizations?status=expired');
    expectError(await capture(b, h.authorization_id), 409, 'authorization_expired');
    expectError(await voidIt(a, h.authorization_id), 409, 'authorization_not_open');
    expectError(await a.post('/payments', { json: { to_handle: 'bob', amount: 10_001 }, key: key() }), 409, 'insufficient_funds');
    expectError(await authorize(a, { to_handle: 'bob', amount: 10_001 }), 409, 'insufficient_funds');
    assert.deepEqual((await request(port, 'GET', '/_test/export')).body, snapshot);
    const p = (await a.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: key() })).body;
    assert.ok(p.created_at > h.created_at);
    assert.equal((await request(port, 'GET', '/_test/export')).body.state.last_ts, p.created_at);
  });
});

describe('funds judged on available (W7.7)', () => {
  it('refuses payments, request payments and settlements that only total would cover', async () => {
    await hold(cy, 'bob', 400); // cy: total 500, available 100
    const k = key();
    expectError(await cy.post('/payments', { json: { to_handle: 'ada', amount: 101 }, key: k }), 409, 'insufficient_funds');
    const rq = (await ada.post('/requests', { json: { payer_handle: 'cy', amount: 150 }, key: key() })).body;
    expectError(await cy.post(`/requests/${rq.request_id}/pay`, { json: {}, key: key() }), 409, 'insufficient_funds');
    expectError(await ada.post('/settlements', {
      json: { transfers: [{ from_handle: 'cy', to_handle: 'ada', amount: 150 }, { from_handle: 'ada', to_handle: 'cy', amount: 49 }] },
      key: key(),
    }), 409, 'insufficient_funds');
    assert.deepEqual(await money(cy), { total: 500, available: 100, held: 400 });

    // Covered by available: each moves money at once and leaves the hold as it was.
    const paid = await cy.post('/payments', { json: { to_handle: 'ada', amount: 100 }, key: k });
    assert.equal(paid.status, 201);
    assert.deepEqual(await money(cy), { total: 400, available: 0, held: 400 });
    const settled = await ada.post('/settlements', {
      json: { transfers: [{ from_handle: 'cy', to_handle: 'ada', amount: 150 }, { from_handle: 'ada', to_handle: 'cy', amount: 150 }] },
      key: key(),
    });
    assert.equal(settled.status, 201, 'a zero net debit needs no available funds');
    await ada.post('/payments', { json: { to_handle: 'cy', amount: 150 }, key: key() });
    assert.equal((await cy.post(`/requests/${rq.request_id}/pay`, { json: {}, key: key() })).status, 201);
    assert.deepEqual(await money(cy), { total: 400, available: 0, held: 400 });
    assert.deepEqual((await list(cy)).map((a) => a.status), ['open']);
  });

  it('a capture may spend the money reserved for it', async () => {
    const a = await hold(cy, 'bob', 500);
    assert.deepEqual(await money(cy), { total: 500, available: 0, held: 500 });
    assert.equal((await capture(bob, a.authorization_id)).status, 201);
    assert.deepEqual(await money(cy), { total: 0, available: 0, held: 0 });
    assert.deepEqual(await money(bob), { total: 3000, available: 3000, held: 0 });
  });
});

describe('reset with authorizations (W7.8)', () => {
  const refused = async (body: Record<string, unknown>, label: string) => {
    const reply = await request(port, 'POST', '/_test/reset', { json: body });
    assert.ok(reply.status === 422 && reply.body?.error?.code === 'validation_failed', `${label}: ${reply.status} ${reply.text}`);
  };

  it('validates authorization_ttl_seconds', async () => {
    for (const ttl of [0, -1, 1.5, '600', null, 10_000_000_001, true]) {
      await refused(fixture({ authorization_ttl_seconds: ttl }), `ttl ${ttl}`);
    }
    assert.equal((await money(ada)).total, 10_000, 'the previous state is intact');
    const literal = JSON.stringify(fixture()).replace(/}$/, ',"authorization_ttl_seconds":600.0}');
    assert.equal((await request(port, 'POST', '/_test/reset', { raw: literal })).status, 204, '600.0 is integral');
    await reset(port, fixture({ authorization_ttl_seconds: 10_000_000_000 }));
    const a = await hold(await login(port, 'ada'), 'bob', 1);
    assert.match(a.expires_at, TS_RE);
    assert.equal(Date.parse(a.expires_at) - Date.parse(a.created_at), 10_000_000_000_000);
  });

  it('refuses every invalid authorization with 422 and keeps the previous state', async () => {
    const base = seedAuth('a_1', 'ada', 'bob', 100);
    const bad: [string, unknown][] = [
      ['not an object', 5], ['no id', { ...base, id: undefined }], ['empty id', { ...base, id: '' }],
      ['long id', { ...base, id: 'x'.repeat(65) }], ['numeric id', { ...base, id: 7 }],
      ['unknown payer', { ...base, from_user_id: 'u_nobody' }], ['unknown receiver', { ...base, to_user_id: 'u_nobody' }],
      ['same party', { ...base, to_user_id: 'u_ada' }], ['negative amount', { ...base, amount: -1 }],
      ['fractional amount', { ...base, amount: 1.5 }], ['huge amount', { ...base, amount: 1_000_000_001 }],
      ['string amount', { ...base, amount: '5' }], ['bad status', { ...base, status: 'OPEN' }],
      ['request status', { ...base, status: 'pending' }], ['negative captured', { ...base, captured_amount: -1 }],
      ['over-captured', { ...base, captured_amount: 101, status: 'captured' }],
      ['fractional captured', { ...base, captured_amount: 1.5 }], ['open and fully captured', { ...base, captured_amount: 100 }],
      ['open with nothing', { ...base, amount: 0 }], ['bad visibility', { ...base, visibility: 'Public' }],
      ['numeric note', { ...base, note: 5 }], ['no expiry', { ...base, expires_at: undefined }],
      ['null expiry', { ...base, expires_at: null }], ['word expiry', { ...base, expires_at: 'tomorrow' }],
      ['no zone', { ...base, expires_at: '2099-01-01T00:00:00' }], ['space', { ...base, expires_at: '2099-01-01 00:00:00Z' }],
      ['Feb 30', { ...base, expires_at: '2099-02-30T00:00:00Z' }], ['Feb 29', { ...base, expires_at: '2099-02-29T00:00:00Z' }],
      ['hour 24', { ...base, expires_at: '2099-01-01T24:00:00Z' }], ['second 60', { ...base, expires_at: '2099-01-01T00:00:60Z' }],
      ['month 13', { ...base, expires_at: '2099-13-01T00:00:00Z' }], ['offset 24h', { ...base, expires_at: '2099-01-01T00:00:00+24:00' }],
      ['empty fraction', { ...base, expires_at: '2099-01-01T00:00:00.Z' }],
      ['too long', { ...base, expires_at: `2099-01-01T00:00:00.${'0'.repeat(45)}Z` }],
      ['numeric payment_id', { ...base, payment_id: 5 }], ['payment_ids not an array', { ...base, payment_ids: 'p_1' }],
      ['payment_ids of numbers', { ...base, payment_ids: [1] }],
      ['duplicate id', [base, { ...base, to_user_id: 'u_cy' }]],
    ];
    for (const [label, entry] of bad) {
      await refused(fixture({ authorizations: Array.isArray(entry) ? entry : [entry] }), label);
    }
    await refused(fixture({ authorizations: 'x' }), 'authorizations not an array');
    await refused(fixture({ payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1, authorization_id: 5 }] }),
      'payment authorization_id');
    assert.equal((await money(ada)).total, 10_000, 'the previous state is intact');
    await reset(port, fixture({ authorizations: [{ ...base, expires_at: '2096-02-29T00:00:00.123456789Z' }] }));
  });

  it('counts seeded unexpired open holds against the balance: equal is fine, above is 422', async () => {
    const users = [user('ada', 1000), user('bob', 0)];
    await refused(fixture({
      users, authorizations: [seedAuth('a_1', 'ada', 'bob', 600), seedAuth('a_2', 'ada', 'bob', 500, { captured_amount: 99 })],
    }), 'remainders 1001 over 1000');
    await reset(port, fixture({
      users,
      authorizations: [
        seedAuth('a_1', 'ada', 'bob', 600), seedAuth('a_2', 'ada', 'bob', 500, { captured_amount: 100 }),
        seedAuth('a_old', 'ada', 'bob', 5000, { expires_at: inHours(-1) }),
        seedAuth('a_cap', 'ada', 'bob', 5000, { status: 'captured' }),
        seedAuth('a_void', 'ada', 'bob', 5000, { status: 'voided', captured_amount: 10 }),
        seedAuth('a_exp', 'ada', 'bob', 5000, { status: 'expired' }),
      ],
    }));
    const a = await login(port, 'ada');
    assert.deepEqual(await money(a), { total: 1000, available: 0, held: 1000 });
    assert.deepEqual(
      (await list(a)).map((x) => [x.authorization_id, x.status, x.captured_amount, x.remaining_amount]),
      [['a_exp', 'expired', 0, 0], ['a_void', 'voided', 10, 0], ['a_cap', 'captured', 5000, 0],
        ['a_old', 'expired', 0, 0], ['a_2', 'open', 100, 400], ['a_1', 'open', 0, 600]],
    );
  });

  it('shows seeded fields as written, with the documented defaults', async () => {
    const lower = '2099-06-01t10:00:00.123456z';
    const offset = '2099-06-01T10:00:00+05:30';
    await reset(port, fixture({
      authorizations: [
        seedAuth('a_1', 'ada', 'bob', 100, { expires_at: lower, note: 'n', visibility: 'private' }),
        seedAuth('a_2', 'ada', 'bob', 100, { expires_at: offset, status: 'captured', payment_id: 'p_x' }),
        seedAuth('a_3', 'ada', 'bob', 100, { status: 'voided', payment_ids: ['p_1', 'p_2'] }),
        seedAuth('a_4', 'ada', 'bob', 100, { status: 'captured', payment_id: null, payment_ids: ['p_9'] }),
        seedAuth('a_5', 'ada', 'bob', 100, { note: null, visibility: null, status: null, captured_amount: null, colour: 1 }),
      ],
      payments: [{ id: 'p_x', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 100, authorization_id: 'a_2' }],
    }));
    const a = await login(port, 'ada');
    const items = await list(a);
    const created = items[0].created_at;
    assert.match(created, TS_RE);
    const view = (x: any) => [x.authorization_id, x.status, x.note, x.visibility, x.expires_at, x.captured_amount,
      x.payment_id, x.payment_ids, x.created_at];
    assert.deepEqual(items.map(view), [
      ['a_5', 'open', '', 'public', items[0].expires_at, 0, null, [], created],
      ['a_4', 'captured', '', 'public', items[1].expires_at, 100, null, ['p_9'], created],
      ['a_3', 'voided', '', 'public', items[2].expires_at, 0, 'p_2', ['p_1', 'p_2'], created],
      ['a_2', 'captured', '', 'public', offset, 100, 'p_x', ['p_x'], created],
      ['a_1', 'open', 'n', 'private', lower, 0, null, [], created],
    ]);
    assert.deepEqual(await money(a), { total: 10_000, available: 9800, held: 200 });
    const [payment] = (await a.get('/activity')).body.payments;
    assert.equal(payment.authorization_id, 'a_2');
  });

  it('a fixture without authorizations behaves as in stage 1', async () => {
    await reset(port, { currency: 'JPY', minor_units: 0, users: [user('ada', 5)] });
    const a = await login(port, 'ada');
    assert.deepEqual(await money(a), { total: 5, available: 5, held: 0 });
    assert.deepEqual(await list(a), []);
    const reply = await a.post('/authorizations', { json: { to_handle: 'ada', amount: 1 }, key: key() });
    expectError(reply, 422, 'self_payment');
  });
});

describe('holds under concurrency (W7.9)', () => {
  it('50 concurrent payments and authorizations from one wallet get exactly what available allows', async () => {
    let reads = 0;
    let stop = false;
    const watch = (async () => {
      while (!stop) {
        const m = await money(ada);
        assert.ok(m.available >= 0 && m.held <= m.total, JSON.stringify(m));
        reads++;
      }
    })();
    const replies = await Promise.all(Array.from({ length: 50 }, (_, i) => i % 2
      ? ada.post('/payments', { json: { to_handle: ['bob', 'cy'][i % 4 >> 1], amount: 300 }, key: key() })
      : authorize(ada, { to_handle: ['bob', 'cy'][i % 4 >> 1], amount: 300 })));
    stop = true;
    await watch;
    assert.ok(reads > 0);
    assert.equal(replies.filter((r) => r.status === 201).length, 33);
    assert.equal(replies.filter((r) => r.status === 409).length, 17);
    const all = await totals();
    assert.equal(sum(all.map((m) => m.total)), 13_000);
    assert.equal(all[0].available, 100);
  });

  it('a concurrent capture and void of one authorization have exactly one winner', async () => {
    for (let round = 0; round < 10; round++) {
      const a = await hold(ada, 'bob', 1000);
      const before = await money(ada);
      const [c, v] = await Promise.all([capture(bob, a.authorization_id, { amount: 600 }), voidIt(ada, a.authorization_id)]);
      const captured = c.status === 201;
      assert.equal(captured, v.status === 409, `${c.status} ${v.status}`);
      assert.equal(!captured, v.status === 200 && c.status === 409);
      const [item] = (await list(ada)).filter((x) => x.authorization_id === a.authorization_id);
      assert.equal(item.status, captured ? 'captured' : 'voided');
      const after = await money(ada);
      assert.equal(after.total, before.total - (captured ? 600 : 0));
      assert.equal(after.held, before.held - 1000);
    }
    assert.equal(sum((await totals()).map((m) => m.total)), 13_000);
  });

  it('20 concurrent nonfinal captures never exceed the authorized amount', async () => {
    const a = await hold(ada, 'bob', 2000);
    const replies = await Promise.all(Array.from({ length: 20 }, () =>
      capture(bob, a.authorization_id, { amount: 150, final: false })));
    const ok = replies.filter((r: Reply) => r.status === 201);
    assert.equal(ok.length, 13);
    for (const r of replies.filter((x: Reply) => x.status !== 201)) expectError(r, 422, 'capture_exceeds_authorization');
    const [item] = await list(ada);
    assert.deepEqual([item.status, item.captured_amount, item.remaining_amount, item.payment_ids.length], ['open', 1950, 50, 13]);
    assert.deepEqual(await money(ada), { total: 8050, available: 8000, held: 50 });
    assert.equal(sum((await totals()).map((m) => m.total)), 13_000);
  });
});
