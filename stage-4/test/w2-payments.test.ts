// W2: the idempotency engine, POST /payments and GET /activity.

import assert from 'node:assert/strict';
import { randomUUID } from 'node:crypto';
import { after, before, beforeEach, describe, it } from 'node:test';
import {
  Client, expectError, fixture, login, request, reset, startServer, user,
  type Server,
} from './helpers.ts';

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
  await reset(port);
  [ada, bob, cy] = await Promise.all([login(port, 'ada'), login(port, 'bob'), login(port, 'cy')]);
});

const key = () => randomUUID();
const pay = (client: Client, json: unknown, k: string = key()) => client.post('/payments', { json, key: k });
const balance = async (client: Client) => (await client.get('/me')).body.balance as number;
const total = async (clients: Client[]) => (await Promise.all(clients.map(balance))).reduce((a, b) => a + b, 0);

describe('POST /payments', () => {
  it('moves money and returns exactly the payment fields', async () => {
    const reply = await pay(ada, { to_handle: 'bob', amount: 1500, note: 'dinner', visibility: 'private' });
    assert.equal(reply.status, 201);
    assert.deepEqual(Object.keys(reply.body).sort(), [
      'amount', 'authorization_id', 'created_at', 'currency', 'from_handle', 'from_user_id', 'note', 'payment_id',
      'refund_of', 'request_id', 'settlement_id', 'to_handle', 'to_user_id', 'visibility',
    ]);
    assert.equal(reply.body.authorization_id, null);
    assert.equal(reply.body.refund_of, null);
    assert.equal(reply.body.from_user_id, 'u_ada');
    assert.equal(reply.body.to_handle, 'bob');
    assert.equal(reply.body.amount, 1500);
    assert.equal(reply.body.currency, 'EUR');
    assert.equal(reply.body.visibility, 'private');
    assert.equal(reply.body.request_id, null);
    assert.equal(reply.body.settlement_id, null);
    assert.match(reply.body.created_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/);
    assert.equal(await balance(ada), 8500);
    assert.equal(await balance(bob), 4000);
  });

  it('defaults note to "" and visibility to public, and keeps notes verbatim', async () => {
    const plain = await pay(ada, { to_handle: 'bob', amount: 1 });
    assert.equal(plain.body.note, '');
    assert.equal(plain.body.visibility, 'public');
    for (const note of ['  café 😀 <b>&amp;</b> ñ  ', 'x'.repeat(200), '😀'.repeat(200), 'e\u0301', '\u0000tab\tnl\n']) {
      const reply = await pay(ada, { to_handle: 'bob', amount: 1, note });
      assert.equal(reply.status, 201);
      assert.equal(reply.body.note, note);
    }
    const feed = await bob.get('/activity', { headers: {} });
    assert.equal(feed.body.payments[0].note, '\u0000tab\tnl\n');
  });

  it('accepts integral number forms and refuses every other amount with 422', async () => {
    for (const raw of ['{"to_handle":"bob","amount":1e3}', '{"to_handle":"bob","amount":1000.0}']) {
      const reply = await ada.post('/payments', { raw, key: key() });
      assert.equal(reply.status, 201, reply.text);
      assert.equal(reply.body.amount, 1000);
    }
    for (const amount of [0, -1, 1.5, 1_000_000_001, 10_000_000_001, '100', true, null, [], {}]) {
      expectError(await pay(ada, { to_handle: 'bob', amount }), 422, 'validation_failed');
    }
    expectError(await pay(ada, { to_handle: 'bob' }), 422, 'validation_failed');
    expectError(await ada.post('/payments', { raw: '{"to_handle":"bob","amount":1e400}', key: key() }), 422, 'validation_failed');
    expectError(await pay(ada, { to_handle: 'bob', amount: 1_000_000_000 }), 409, 'insufficient_funds');
  });

  it('applies the note, visibility and handle rules', async () => {
    for (const note of [null, 5, 'x'.repeat(201), '😀'.repeat(201)]) {
      expectError(await pay(ada, { to_handle: 'bob', amount: 1, note }), 422, 'validation_failed');
    }
    for (const visibility of ['Public', '', null, 'secret', 1]) {
      expectError(await pay(ada, { to_handle: 'bob', amount: 1, visibility }), 422, 'validation_failed');
    }
    for (const toHandle of [null, 5, ['bob']]) {
      expectError(await pay(ada, { to_handle: toHandle, amount: 1 }), 400, 'malformed_request');
    }
    expectError(await pay(ada, { amount: 1 }), 422, 'validation_failed');
    for (const toHandle of ['nobody', 'ADA', '@ada', '', 'bob ']) {
      expectError(await pay(ada, { to_handle: toHandle, amount: 1 }), 404, 'not_found');
    }
    expectError(await pay(ada, { to_handle: 'ada', amount: 1 }), 422, 'self_payment');
    assert.equal((await pay(ada, { to_handle: 'bob', amount: 1, colour: 'blue' })).status, 201);
  });

  it('refuses a payment above the balance and changes nothing', async () => {
    expectError(await pay(cy, { to_handle: 'bob', amount: 501 }), 409, 'insufficient_funds');
    assert.equal(await balance(cy), 500);
    assert.deepEqual((await cy.get('/activity')).body.payments, []);
    assert.equal((await pay(cy, { to_handle: 'bob', amount: 500 })).status, 201);
    assert.equal(await balance(cy), 0);
  });

  it('refuses to take a receiver above 2^53 and changes nothing', async () => {
    await reset(port, fixture({ users: [user('ada', 100), user('rich', 2 ** 53 - 10)] }));
    const a = await login(port, 'ada');
    expectError(await pay(a, { to_handle: 'rich', amount: 11 }), 422, 'validation_failed');
    assert.equal(await balance(a), 100);
    assert.equal((await pay(a, { to_handle: 'rich', amount: 10 })).status, 201);
    const rich = await login(port, 'rich');
    assert.equal(await balance(rich), 2 ** 53);
  });

  it('checks precedence: auth, key, body, claimed key, fields', async () => {
    expectError(await request(port, 'POST', '/payments', { raw: '{nope' }), 401, 'unauthenticated');
    expectError(await ada.post('/payments', { raw: '{nope' }), 400, 'missing_idempotency_key');
    expectError(await ada.post('/payments', { raw: '{nope', key: '' }), 400, 'missing_idempotency_key');
    expectError(await ada.post('/payments', { raw: '{nope', key: 'k'.repeat(256) }), 422, 'validation_failed');
    expectError(await ada.post('/payments', { json: { to_handle: 'bob', amount: 1 }, key: 'k'.repeat(10_000) }),
      422, 'validation_failed');
    assert.equal((await pay(ada, { to_handle: 'bob', amount: 1 }, 'k'.repeat(255))).status, 201);
    // A UTF-8 key travels as raw header bytes; 255 emoji are 255 characters.
    const emojiKey = (n: number) => Buffer.from('😀'.repeat(n)).toString('latin1');
    assert.equal((await pay(ada, { to_handle: 'bob', amount: 1 }, emojiKey(255))).status, 201);
    expectError(await pay(ada, { to_handle: 'bob', amount: 1 }, emojiKey(256)), 422, 'validation_failed');
    expectError(await ada.post('/payments', { raw: '{nope', key: key() }), 400, 'malformed_request');
    const k = key();
    assert.equal((await pay(ada, { to_handle: 'bob', amount: 1 }, k)).status, 201);
    expectError(await pay(ada, { to_handle: 'bob', amount: 'nonsense' }, k), 409, 'idempotency_key_reuse');
    expectError(await pay(ada, { to_handle: 'ada', amount: 1 }, k), 409, 'idempotency_key_reuse');
  });
});

describe('idempotency on POST /payments', () => {
  it('replays with 200 and the original body, and moves money once', async () => {
    const k = key();
    const first = await pay(ada, { to_handle: 'bob', amount: 300, note: 'n' }, k);
    assert.equal(first.status, 201);
    const replay = await pay(ada, { note: 'n', amount: 300, to_handle: 'bob' }, k);
    assert.equal(replay.status, 200);
    assert.deepEqual(replay.body, first.body);
    const spaced = await ada.post('/payments', { raw: ' { "amount" : 3e2 , "to_handle":"bob","note":"n"} ', key: k });
    assert.equal(spaced.status, 200);
    assert.deepEqual(spaced.body, first.body);
    assert.equal(await balance(ada), 9700);
  });

  it('returns the original after the balance changed, and 409 for a different body', async () => {
    const k = key();
    const first = await pay(ada, { to_handle: 'bob', amount: 9000 }, k);
    await pay(ada, { to_handle: 'cy', amount: 1000 });
    assert.equal(await balance(ada), 0);
    const replay = await pay(ada, { to_handle: 'bob', amount: 9000 }, k);
    assert.equal(replay.status, 200);
    assert.deepEqual(replay.body, first.body);
    expectError(await pay(ada, { to_handle: 'bob', amount: 9001 }, k), 409, 'idempotency_key_reuse');
    expectError(await pay(ada, { to_handle: 'bob', amount: 9000, visibility: 'public' }, k), 409, 'idempotency_key_reuse');
    assert.equal(await total([ada, bob, cy]), 13_000);
  });

  it('scopes keys per user; a key that failed with 4xx is a first use later', async () => {
    const k = 'same-string';
    assert.equal((await pay(ada, { to_handle: 'bob', amount: 10 }, k)).status, 201);
    assert.equal((await pay(bob, { to_handle: 'cy', amount: 10 }, k)).status, 201);
    const failed = key();
    expectError(await pay(cy, { to_handle: 'bob', amount: 600 }, failed), 409, 'insufficient_funds');
    expectError(await pay(cy, { to_handle: 'bob', amount: 1, note: null }, failed), 422, 'validation_failed');
    assert.equal((await pay(cy, { to_handle: 'bob', amount: 20 }, failed)).status, 201);
  });

  it('50 concurrent identical first uses give one 201 and 49 identical 200s', async () => {
    const k = key();
    const replies = await Promise.all(Array.from({ length: 50 }, () => pay(ada, { to_handle: 'bob', amount: 100 }, k)));
    assert.equal(replies.filter((r) => r.status === 201).length, 1);
    assert.equal(replies.filter((r) => r.status === 200).length, 49);
    const first = replies.find((r) => r.status === 201)!;
    for (const r of replies) assert.deepEqual(r.body, first.body);
    assert.equal(await balance(ada), 9900);
    assert.equal((await ada.get('/activity')).body.payments.length, 1);
  });
});

describe('money under load', () => {
  it('a wallet drained in parts by 50 concurrent payments', async () => {
    await reset(port, fixture({ users: [user('ada', 1000), user('bob', 0)] }));
    const clients = await Promise.all(Array.from({ length: 50 }, () => login(port, 'ada')));
    const replies = await Promise.all(clients.map((c) => pay(c, { to_handle: 'bob', amount: 30 })));
    const ok = replies.filter((r) => r.status === 201).length;
    assert.equal(ok, Math.floor(1000 / 30));
    for (const r of replies.filter((x) => x.status !== 201)) expectError(r, 409, 'insufficient_funds');
    const b = await login(port, 'bob');
    assert.equal(await balance(clients[0]), 1000 - 30 * ok);
    assert.equal(await balance(b), 30 * ok);
  });

  it('three wallets paying around a cycle stay conserved and non-negative', async () => {
    const pairs: Array<[Client, string]> = [[ada, 'bob'], [bob, 'cy'], [cy, 'ada']];
    const replies = await Promise.all(Array.from({ length: 60 }, (_, i) => {
      const [from, to] = pairs[i % 3];
      return pay(from, { to_handle: to, amount: 200 });
    }));
    for (const r of replies) assert.ok(r.status === 201 || r.status === 409, r.text);
    const balances = await Promise.all([ada, bob, cy].map(balance));
    assert.ok(balances.every((b) => b >= 0));
    assert.equal(balances.reduce((a, b) => a + b, 0), 13_000);
  });

  it('conservation across 50 wallets', async () => {
    const users = Array.from({ length: 50 }, (_, i) => user(`w${i}`, 100 + i));
    await reset(port, fixture({ users }));
    const clients = await Promise.all(users.map((u) => login(port, u.handle as string)));
    const replies = await Promise.all(clients.map((c, i) => pay(c, { to_handle: `w${(i * 7 + 3) % 50}`, amount: 60 + i })));
    for (const r of replies) assert.ok(r.status === 201 || r.status === 409 || r.status === 422, r.text);
    const expected = users.reduce((a, u) => a + (u.balance as number), 0);
    const balances = await Promise.all(clients.map(balance));
    assert.ok(balances.every((b) => b >= 0));
    assert.equal(balances.reduce((a, b) => a + b, 0), expected);
  });
});

describe('GET /activity', () => {
  it('shows a payment iff it is public or the caller is a party', async () => {
    const pub = (await pay(ada, { to_handle: 'bob', amount: 1, visibility: 'public' })).body;
    const priv = (await pay(ada, { to_handle: 'bob', amount: 2, visibility: 'private' })).body;
    assert.deepEqual((await cy.get('/activity')).body, { payments: [pub], has_more: false });
    assert.deepEqual((await ada.get('/activity')).body.payments, [priv, pub]);
    assert.deepEqual((await bob.get('/activity')).body.payments, [priv, pub]);
  });

  it('shows seeded payments by the same rule', async () => {
    await reset(port, fixture({
      payments: [
        { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, note: 'coffee', visibility: 'private' },
        { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_ada', amount: 5 },
      ],
    }));
    const c = await login(port, 'cy');
    const a = await login(port, 'ada');
    const third = (await c.get('/activity')).body.payments;
    assert.deepEqual(third.map((p: any) => p.payment_id), ['p_2']);
    assert.equal(third[0].note, '');
    assert.equal(third[0].visibility, 'public');
    assert.deepEqual((await a.get('/activity')).body.payments.map((p: any) => p.payment_id), ['p_2', 'p_1']);
  });

  it('is newest first and pages with limit, offset and has_more', async () => {
    const made = [];
    for (let i = 0; i < 5; i++) made.push((await pay(ada, { to_handle: 'bob', amount: 10 + i })).body);
    const all = (await cy.get('/activity')).body.payments;
    assert.deepEqual(all, made.slice().reverse());
    const times = all.map((p: any) => p.created_at);
    assert.deepEqual(times, times.slice().sort().reverse());
    assert.deepEqual((await cy.get('/activity?limit=2')).body, { payments: all.slice(0, 2), has_more: true });
    assert.deepEqual((await cy.get('/activity?limit=2&offset=2')).body, { payments: all.slice(2, 4), has_more: true });
    assert.deepEqual((await cy.get('/activity?limit=2&offset=4')).body, { payments: all.slice(4), has_more: false });
    assert.deepEqual((await cy.get('/activity?offset=99999999999999999999')).body, { payments: [], has_more: false });
    assert.deepEqual((await cy.get('/activity?limit=200&direction=both&status=open&x=1')).body.payments, all);
    assert.deepEqual((await cy.get('/activity?limit=1&limit=500')).body.payments.length, 1);
  });

  it('refuses invalid paging values with 422', async () => {
    for (const q of ['limit=0', 'limit=201', 'limit=-5', 'limit=1e9', 'limit=4.0', 'limit=%2B4', 'limit=', 'limit=abc',
      'offset=-1', 'offset=abc', 'offset=1.0', 'offset=']) {
      expectError(await ada.get(`/activity?${q}`), 422, 'validation_failed');
    }
    expectError(await request(port, 'GET', '/activity'), 401, 'unauthenticated');
  });
});
